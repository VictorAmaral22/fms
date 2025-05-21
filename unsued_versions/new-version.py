import subprocess
import time
import psutil
import threading
import os

# C:\Program Files (x86)\Steam\steam.exe
# C:\Program Files (x86)\Microsoft\Edge\Application

class FMS:
    def __init__(self):
        self.total_cpu_quota = 0.0
        self.cpu_consumed = 0.0
        self.active = True
        self.verification_loop_time_in_seconds = 1
        self.active_processes = []
        self.active_monitors = []
    
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

    def start_process(self, binary_path=None, args=None):
        try:
            # Inicia o processo FMS
            print(f"Tentando executar: '{binary_path} {' '.join(args)}'")
            popen = subprocess.Popen(
                [binary_path] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print("Processo FMS iniciado com PID:", popen.pid)
            self.active_processes.append(popen)
            print(f"Processo piroca {popen.pid} lançado.")
        except Exception as e:
            print(f"Erro ao iniciar o processo FMS: {e}")

    def monitor_total_cpu_usage(self, stop_event):
        print("Monitorando uso de CPU...")
        while not stop_event.is_set():

            
            for proc in self.active_processes:
                print(proc)
                # try:  
                # process = psutil.Process(proc.pid)      
                # cpu_time = process.cpu_times().user + process.cpu_times().system
                # print(cpu_time)

                #     process = psutil.Process(proc.pid)
                #     self.cpu_consumed += cpu_time
                #     print(f"\nTempo de uso de CPU do processo {proc.pid}: {cpu_time}s")
                #     if self.cpu_consumed >= self.total_cpu_quota:
                #         print("Limite de tempo de uso de CPU atingido. Encerrando o processo.")
                #         stop_event.set()
                #         process.terminate()
                #         try:
                #             proc.wait(timeout=3)
                #         except subprocess.TimeoutExpired:
                #             proc.kill()
                #         self.active_processes.remove(proc)
                #         break
                # except Exception as e:
                #     print(f"Erro ao monitorar o processo {proc.pid}: {e}")
                #     stop_event.set()
                #     break
                time.sleep(self.verification_loop_time_in_seconds)

    def run(self):
        print("Iniciando o sistema FMS...")
        self.total_cpu_quota = float(input("Informe a quota TOTAL de tempo de CPU para o FMS em segundos: "))
        print("=========================================================")

        try:
            while self.cpu_consumed < self.total_cpu_quota and self.active:
                command, proc_cpu, proc_timeout, proc_mem, should_exit = self.get_params()
                if should_exit:
                    print("Saindo do FMS.")
                    self.active = False
                    break

                if command is None:
                    time.sleep(self.verification_loop_time_in_seconds)
                    continue  

                binary_path, args = command
                try:
                    self.start_process(binary_path, args)
                    stop_event = threading.Event()
                    thread = threading.Thread(
                        target=self.monitor_total_cpu_usage,
                        args=(
                            stop_event
                        ),
                    )
                    thread.start()
                    self.active_monitors.append(thread)
                except KeyboardInterrupt:
                    print("Execução interrompida pelo usuário.")
                    break
        finally:
            print("\n--- FMS Finalizando ---")
            print(f"CPU total FMS consumida: {self.cpu_consumed:.2f}s")
            print("--- FMS Encerrado. ---")
            

if __name__ == "__main__":
    fms_system = FMS()
    try:
        fms_system.run()
    except Exception as e:
        print(f"\nERRO CRÍTICO NO FMS: {e}")
    finally:
        print("Programa principal FMS finalizado.")
