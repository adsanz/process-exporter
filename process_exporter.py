#!/usr/local/bin/python3

import time
import logging
from prometheus_client import start_http_server, Gauge, CollectorRegistry
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
SCRAPE_TIME = os.environ.get('SCRAPE_TIME', 10)
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
        self.registry = CollectorRegistry()
        self.host = socket.gethostname()
        self.ram_metric = Gauge("memory_usage_bytes", "Memory used om bytes.",
            labelnames=['host', 'proc_name', 'proc_cmdline', 'proc_pid', 'type'], registry=self.registry)
        self.cpu_metric = Gauge("cpu_usage_percent", "CPU usage percent. Note that value can be greater than 100%. if a proces is using multiple cores.",
            labelnames=['host', 'proc_name', 'proc_cmdline', 'proc_pid'], registry=self.registry)
        self.ram_total = Gauge("memory_total_bytes", "Total memory in bytes.",
            labelnames=['host'], registry=self.registry)
        
        super().__init__()


    def judge(self, prom_response, procs, type):
        """Compare the metrics on prometheus with the running processes and set to 0 the metrics of the processes that are not running and remove the labelset from prometheus"""

        proc_pid_list = [p.pid for p in procs]

        for metric in prom_response:
            proc_pid = int(metric['metric']['proc_pid'])
            if proc_pid not in proc_pid_list:
                name = metric['metric']['proc_name']
                cmdline = metric['metric']['proc_cmdline']
                host = metric['metric']['host']

                if type == "cpu":
                    logging.warning(f'[CPU JUDGE] Process {name} ({proc_pid}) not found on system, removing labelset from prometheus')
                    self.cpu_metric.labels(host, name, str(cmdline), proc_pid).set(0)
                    self.cpu_metric.remove(host, name, str(cmdline), proc_pid)
                elif type == "ram":
                    logging.warning(f'[RAM JUDGE] Process {name} ({proc_pid}) not found on system, removing labelset from prometheus')
                    self.ram_metric.labels(host, name, str(cmdline), proc_pid, 'used').set(0)
                    self.ram_metric.labels(host, name, str(cmdline), proc_pid, 'swap').set(0)
                    self.ram_metric.remove(host, name, str(cmdline), proc_pid, 'used')
                    self.ram_metric.remove(host, name, str(cmdline), proc_pid, 'swap')

    def cleaner(self, procs):
        """Call prometheus to set to 0 the metrics of the processes that are not running"""

        prom = PrometheusConnect(url=PROMETHEUS, disable_ssl=True)
        host_format = "{" + f'host="{self.host}"' + "}"
        cpu = prom.custom_query(query=f"cpu_usage_percent{host_format} != 0")
        logging.info(f'[CLEANER] Found {len(cpu)} cpu metrics on prometheus')
        ram = prom.custom_query(query=f"memory_usage_bytes{host_format} != 0")
        logging.info(f'[CLEANER] Found {len(ram)} ram metrics on prometheus')
        if len(cpu) > 0:
            self.judge(cpu, procs, "cpu")
        if len(ram) > 0:
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
            time.sleep(SCRAPE_TIME)
            self.metrics.cleaner(procs)

            


def main():
    """Main entry point"""
    exporter_port = os.getenv("EXPORTER_PORT", 9877)
    logging.info(f"Starting exporter on port {exporter_port}")
    logging.info(f"Prometheus host: {PROMETHEUS}")
    metric_manager = MetricManager()
    start_http_server(exporter_port, registry=metric_manager.metrics.registry)
    metric_manager.run_metrics_loop()

if __name__ == "__main__":
    main()
