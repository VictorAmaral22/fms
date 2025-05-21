import subprocess
import time
import psutil
import threading
import os

class FMS:
    def __init__(self):
        self.total_cpu_quota = 0.0
        self.cpu_consumed = 0.0
        self.active = True

    def init_config(self):
        self.total_cpu_quota = float(
            input(
                "Informe a quota TOTAL de tempo de CPU para o FMS em segundos: "
            )
        )
        print("=========================================================")

    def get_params(self):
        print("\n--- Novo Programa para Execução ---")
        binary_input = input(
            "Programa e args, ou 'sair' para encerrar: "
        )

        if not binary_input.strip():
            print("Nenhum binário fornecido desta vez.")
            return None, None, None, None, False

        if binary_input.lower() == "sair":
            return None, None, None, None, True

        try:
            command_parts = binary_input.strip().split()
            if not command_parts:
                print("Comando inválido.")
                return None, None, None, None, False
            binary_path = command_parts[0]
            args = command_parts[1:]
        except Exception as e:
            print(f"Erro ao processar o comando: {e}")
            return None, None, None, None, False


        cpu_input = input("Quota CPU para binário (s, branco=sem limite): ")
        cpu_limit_process = float(cpu_input) if cpu_input else None

        timeout_input = input("Timeout para o binário (s, branco=sem limite): ")
        timeout_in_seconds = float(timeout_input) if timeout_input else None

        memory_limit = input("Quantidade de Memória para o binário (MB, branco=sem limite): ")
        memory_limit_mb = None
        
        if memory_limit:
            try:
                memory_limit = float(memory_limit)
                if memory_limit <= 0:
                    print("Limite de memória deve ser positivo.")
                else:
                    memory_limit_mb = memory_limit * 1024 * 1024
            except ValueError:
                print("Entrada de memória inválida.")

        print("=========================================================")
        return (
            (binary_path, args),
            cpu_limit_process,
            timeout_in_seconds,
            memory_limit_mb,
            False,
        )

    def process_monitor(
        self,
        ps_process: psutil.Process,
        process_cpu_limit,
        process_memory_mb_limit,
        process_timeout_in_seconds,
        stop_event: threading.Event,
        result_dict: dict,
    ):
        pid = ps_process.pid
        result_dict.update(
            {
                "pid": pid,
                "status": "running",
                "reason": "",
                "cpu_time_used": 0.0,
                "max_memory": 0,
                "timeout_time": 0.0,
                "terminate_fms_due_to_memory": False,
            }
        )

        start_time = time.monotonic()
        initial_cpu_times = None
        try:
            if ps_process.is_running():
                initial_cpu_times = ps_process.cpu_times()
            else:
                result_dict["status"] = "terminated_early"
                result_dict["reason"] = "Processo terminou antes do monitoramento."
                return
        except psutil.Error as e:
            result_dict["status"] = "terminated_early_error"
            result_dict["reason"] = f"Erro ao iniciar monitoramento: {e}"
            return

        try:
            while ps_process.is_running() and not stop_event.is_set():
                current_time = time.monotonic()
                result_dict["timeout_time"] = (
                    current_time - start_time
                )

                if (
                    process_timeout_in_seconds is not None
                    and result_dict["timeout_time"]
                    > process_timeout_in_seconds
                ):
                    result_dict["status"] = "timeout"
                    result_dict["reason"] = "Timeout atingido."
                    ps_process.terminate()
                    ps_process.wait(timeout=0.5)
                    return

                current_cpu_times = None
                current_memory = 0
                try:
                    if not ps_process.is_running():
                        break
                    current_cpu_times = ps_process.cpu_times()
                    current_memory = ps_process.memory_info().rss
                except psutil.Error:
                    break

                if initial_cpu_times and current_cpu_times:
                    result_dict["cpu_time_used"] = (
                        current_cpu_times.user - initial_cpu_times.user
                    ) + (current_cpu_times.system - initial_cpu_times.system)

                if current_memory > result_dict["max_memory"]:
                    result_dict["max_memory"] = current_memory

                if (
                    process_memory_mb_limit is not None
                    and result_dict["max_memory"] > process_memory_mb_limit
                ):
                    result_dict["status"] = "memory_exceeded"
                    result_dict["reason"] = "Limite de memória excedido."
                    result_dict["terminate_due_to_memory"] = True
                    ps_process.terminate()
                    ps_process.wait(timeout=0.5)
                    return

                if (
                    process_cpu_limit is not None
                    and result_dict["cpu_time_used"] > process_cpu_limit
                ):
                    result_dict["status"] = "cpu_exceeded_process"
                    result_dict["reason"] = "Quota de CPU do processo excedida."
                    ps_process.terminate()
                    ps_process.wait(timeout=0.5)
                    return

                time.sleep(1.0)

            if (
                result_dict["status"] == "running"
            ):
                result_dict["status"] = (
                    "completed" if not stop_event.is_set() else "terminated_by_fms"
                )
        except psutil.Error as e:
            result_dict["status"] = "monitoring_error"
            result_dict["reason"] = f"Erro psutil: {e}"
        except Exception as e:
            result_dict["status"] = "critical_error"
            result_dict["reason"] = f"Erro inesperado: {e}"
        finally:
            result_dict["timeout_time"] = (
                time.monotonic() - start_time
            )
            if initial_cpu_times and ps_process:
                try:
                    final_cpu_times = (
                        ps_process.cpu_times()
                    ) 
                    result_dict["cpu_time_used"] = (
                        final_cpu_times.user - initial_cpu_times.user
                    ) + (final_cpu_times.system - initial_cpu_times.system)
                except psutil.Error:
                    pass

            print(
                f"[{pid}] Monitor FIM. Status: {result_dict.get('status','N/A')}. CPU: {result_dict.get('cpu_time_used',0):.4f}s. Mem: {result_dict.get('max_memory',0)/(1024*1024):.4f}MB."
            )

    def monitor_cpu_time(self, verification_loop_time_in_seconds):
        while self.cpu_consumed < self.total_cpu_quota:
            time.sleep(verification_loop_time_in_seconds)

        if self.cpu_consumed >= self.total_cpu_quota:
            print(
                f"\nFMS ENCERRANDO: Quota total de CPU ({self.total_cpu_quota:.4f}s) esgotada."
            )
            self.active = False

    def run(self):
        self.init_config()
        print(f"\nFMS iniciado. Quota total CPU: {self.total_cpu_quota:.4f}s.")

        active_jobs = []
        verification_loop_time_in_seconds = 0.5

        # Start CPU quota monitoring thread
        cpu_time_thread = threading.Thread(
            target=self.monitor_cpu_time,
            name="MONITOR_CPU_TIME",
            args=[verification_loop_time_in_seconds],
            daemon=True
        )
        cpu_time_thread.start()

        def print_active_jobs_status():
            if not active_jobs:
                return
                
            print("\n=== Status dos Processos Ativos ===")
            for job in active_jobs:
                # Update process info before printing
                try:
                    if job["psutil"].is_running():
                        current_cpu_times = job["psutil"].cpu_times()
                        current_memory = job["psutil"].memory_info().rss
                        initial_cpu_times = job["initial_cpu_times"]
                        
                        # Update results dictionary with current values
                        results = job["results_dict"]
                        results["cpu_time_used"] = (
                            (current_cpu_times.user - initial_cpu_times.user) +
                            (current_cpu_times.system - initial_cpu_times.system)
                        )
                        results["max_memory"] = max(current_memory, results.get("max_memory", 0))
                        results["timeout_time"] = time.monotonic() - job["start_time"]
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

                results = job["results_dict"]
                print(
                    f"[PID {results.get('pid','N/A')}] "
                    f"'{job['binary_path']}': "
                    f"CPU={results.get('cpu_time_used',0):.2f}s, "
                    f"Mem={results.get('max_memory',0)/(1024*1024):.2f}MB, "
                    f"Tempo={results.get('timeout_time',0):.2f}s"
                )
            print("=================================")

        try:
            print("\n--- FMS Iniciando ---")
            last_status_print = time.monotonic()
            
            while self.active:
                current_time = time.monotonic()
                
                # Print status every second if there are active jobs
                if active_jobs and current_time - last_status_print >= 1.0:
                    print_active_jobs_status()
                    last_status_print = current_time

                # Get parameters for new process
                command, proc_cpu, proc_timeout, proc_mem, should_exit = self.get_params()

                if should_exit:
                    self.active = False
                    break

                if command is None:
                    # Check existing jobs status
                    time.sleep(verification_loop_time_in_seconds if active_jobs else 1.0)
                else:
                    # Launch new process
                    binary_path, args = command
                    try:
                        print(f"Tentando executar: '{binary_path} {' '.join(args)}'")
                        popen = subprocess.Popen(
                            [binary_path] + args,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                        ps_proc = psutil.Process(popen.pid)
                        print(f"Processo {popen.pid} lançado.")

                        # Setup monitoring
                        results = {}
                        stop_event = threading.Event()
                        thread = threading.Thread(
                            target=self.process_monitor,
                            args=(ps_proc, proc_cpu, proc_mem, proc_timeout, stop_event, results),
                            daemon=True
                        )
                        thread.start()

                        initial_cpu_times = ps_proc.cpu_times()
                        active_jobs.append({
                            "popen": popen,
                            "psutil": ps_proc,
                            "thread": thread,
                            "stop_event": stop_event,
                            "results_dict": results,
                            "binary_path": binary_path,
                            "initial_cpu_times": initial_cpu_times,  # Add initial CPU times
                            "start_time": time.monotonic(),  # Add start time
                        })

                    except Exception as e:
                        print(f"Erro ao lançar '{binary_path}': {e}")
                        continue

                # Monitor active jobs
                for job in active_jobs[:]:  # Create a copy of the list for iteration
                    if not job["thread"].is_alive():
                        if job["popen"].returncode is None:
                            job["popen"].wait(timeout=0.01)

                        results = job["results_dict"]
                        print(
                            f"\n--- Relatório: '{job['binary_path']}' (PID: {results.get('pid', 'N/A')}) ---"
                        )
                        print(
                            f"  Status: {results.get('status','N/A')}, Razão: {results.get('reason','N/A')}"
                        )
                        print(
                            f"  Saída: {job['popen'].returncode}, CPU: {results.get('cpu_time_used',0):.4f}s, "
                            f"MemPico: {results.get('max_memory',0)/(1024*1024):.4f}MB, "
                            f"WallT: {results.get('timeout_time',0):.4f}s"
                        )
                        print("-------------------------------------------")

                        # Update CPU quota only for successful executions
                        if results.get('status') not in ['terminated_early', 'terminated_early_error']:
                            self.cpu_consumed += results.get("cpu_time_used", 0.0)
                            print(f"CPU total consumida até agora: {self.cpu_consumed:.4f}s / {self.total_cpu_quota:.4f}s")

                        if results.get("terminate_fms_due_to_memory", False):
                            print("\nFMS ENCERRANDO: Processo excedeu limite de memória.")
                            self.active = False
                            break

                        active_jobs.remove(job)

                time.sleep(0.1)  # Keep short sleep for responsiveness

        except KeyboardInterrupt:
            print("\nFMS interrompido (Ctrl+C).")
            self.active = False
        finally:
            print("\n--- FMS Finalizando ---")
            if active_jobs:
                print(f"Parando {len(active_jobs)} processo(s) ativo(s)...")
                for job in active_jobs:
                    job["stop_event"].set()
                    if job["psutil"].is_running():
                        try:
                            job["psutil"].terminate()
                            job["psutil"].wait(timeout=0.5)
                        except psutil.Error:
                            try:
                                job["psutil"].kill()
                            except psutil.Error:
                                pass
                    job["thread"].join(timeout=2.0)
            print(f"CPU total FMS consumida: {self.cpu_consumed:.4f}s")
            print("--- FMS Encerrado. ---")


if __name__ == "__main__":
    fms_system = FMS()
    try:
        fms_system.run()
    except Exception as e:
        print(f"\nERRO CRÍTICO NO FMS: {e}")
    finally:
        print("Programa principal FMS finalizado.")
