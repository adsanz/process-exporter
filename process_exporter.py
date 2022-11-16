#!/usr/local/bin/python3

import time
import logging
from prometheus_client import start_http_server, Gauge
import prometheus_client
import socket
import psutil
import os
from prometheus_api_client import PrometheusConnect

# Disable default collectors
prometheus_client.REGISTRY.unregister(prometheus_client.GC_COLLECTOR)
prometheus_client.REGISTRY.unregister(prometheus_client.PLATFORM_COLLECTOR)
prometheus_client.REGISTRY.unregister(prometheus_client.PROCESS_COLLECTOR)

# OS ENV
PROMETHEUS = os.environ.get('PROMETHEUS_HOST', 'http://localhost:9090')
psutil.PROCFS_PATH = "/proc_container"
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')

class GatherMetrics():
    """
    Representation of Prometheus metrics and loop to fetch and transform
    application metrics into Prometheus metrics.
    """

    def __init__(self):
        """
        Initialize labels for metrics
        """
        self.host = socket.gethostname()
        self.ram_metric = Gauge("memory_usage_bytes", "Memory used om bytes.",
            labelnames=['host', 'proc_name', 'proc_cmdline', 'proc_pid', 'type'])
        self.cpu_metric = Gauge("cpu_usage_percent", "CPU usage percent. Note that value can be greater than 100%. if a proces is using multiple cores.",
            labelnames=['host', 'proc_name', 'proc_cmdline', 'proc_pid'])
        self.ram_total = Gauge("memory_total_bytes", "Total memory in bytes.",
            labelnames=['host'])
        
        super().__init__()

    def judge(self, prom_response, procs, type):
        """First check if the value is 0 for metric gathered, if not then check if it's on the procs list, if not then set to 0"""
        proc_pid_list = [p.pid for p in procs]

        for metric in prom_response:
            metric_pid = int(metric['metric']['proc_pid'])
            if metric_pid not in proc_pid_list:
                if type == "cpu":
                    logging.warning(f'[CPU JUDGE] Process {metric["metric"]["proc_pid"]} cpu not found on system, setting value to 0 on prometheus')
                    self.cpu_metric.labels(self.host, metric['metric']['proc_name'],metric['metric']['proc_cmdline'], metric['metric']['proc_pid']).set(0)
                elif type == "ram":
                    logging.warning(f'[RAM JUDGE] Process {metric["metric"]["proc_pid"]} not found on system, setting value to 0 on prometheus')
                    self.ram_metric.labels(self.host, metric['metric']['proc_name'],metric['metric']['proc_cmdline'], metric['metric']['proc_pid'], 'used').set(0)
                    self.ram_metric.labels(self.host, metric['metric']['proc_name'],metric['metric']['proc_cmdline'], metric['metric']['proc_pid'], 'swap').set(0)

    def cleaner(self, procs):
        """Call prometheus to set to 0 the metrics of the processes that are not running"""

        prom = PrometheusConnect(url=PROMETHEUS, disable_ssl=True)
        host_format = "{" + f'host="{self.host}"' + "}"
        cpu = prom.custom_query(query=f"cpu_usage_percent{host_format} != 0")
        ram = prom.custom_query(query=f"memory_usage_bytes{host_format} != 0")

        self.judge(cpu, procs, "cpu")
        self.judge(ram, procs, "ram")


    def fetch(self, procs):
        """Gathers the metrics"""

        ram = psutil.virtual_memory()
        self.ram_total.labels(self.host).set(ram.total)
        for proc in procs:

            try:
                with proc.oneshot():
                    cpu_usage = proc.cpu_percent(interval=None) 
                    self.ram_metric.labels(self.host, proc.info['name'], proc.info['cmdline'], proc.info['pid'], 'used').set(proc.memory_full_info().uss)
                    self.ram_metric.labels(self.host, proc.info['name'], proc.info['cmdline'], proc.info['pid'], 'swap').set(proc.memory_full_info().swap)
                    self.cpu_metric.labels(self.host, proc.info['name'], proc.info['cmdline'], proc.info['pid']).set(cpu_usage)
            except psutil.NoSuchProcess or psutil.ZombieProcess:
                continue




class MetricManager:
    def __init__(self):
        self.metrics = GatherMetrics()

    def run_metrics_loop(self):
        """Metrics fetching loop"""
        while True:
            procs = {p for p in psutil.process_iter(['name', 'cmdline', 'pid'])}
            logging.info("Starting metrics loop")
            self.metrics.fetch(procs)
            time.sleep(5)
            self.metrics.cleaner(procs)

            


def main():
    """Main entry point"""
    exporter_port = os.getenv("EXPORTER_PORT", 9877)

    metric_manager = MetricManager()
    start_http_server(exporter_port)
    metric_manager.run_metrics_loop()

if __name__ == "__main__":
    main()
