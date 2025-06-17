#Membros Christian / Victor / Eric
#Instruções:
# 1. Instale as dependências necessárias: `pip install psutil prompt_toolkit`
# 2. Execute o script: `python main.py`

import subprocess
import psutil
import time
import threading
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

# class CreditManager: responsavel por gerenciar os créditos de CPU
class CreditManagerPrePago:
    total_credits = 0
    # Usando um lock para garantir que o acesso aos créditos seja thread-safe
    # Isso é importante para evitar condições de corrida quando múltiplas threads tentam acessar ou modificar o saldo ao mesmo tempo.
    lock = threading.Lock()

    # Método de classe para definir o total de créditos disponíveis
    @classmethod
    def set_total(cls, value):
        with cls.lock:
            cls.total_credits = value

    # Método de classe para debitar créditos
    # Verifica se há créditos suficientes antes de debitar
    @classmethod
    def debit(cls, amount):
        with cls.lock:
            if cls.total_credits >= amount:
                cls.total_credits -= amount
                return True
            return False

    # Método de classe para pegar o total de créditos disponíveis
    @classmethod
    def get_balance(cls):
        with cls.lock:
            return cls.total_credits

class FMS:
    total_cpu_used = 0
    # Usando um lock para garantir que o acesso ao total de CPU usada seja thread-safe
    # Isso é importante para evitar condições de corrida quando múltiplas threads tentam acessar ou modificar o total da cpu ao mesmo tempo.
    total_cpu_lock = threading.Lock()

    def __init__(self, pre_pago=True):
        self.limit_cpu = 0
        self.limit_mem = 0
        self.limit_time = 0
        self.process = None
        self.proc_cpu_time = 0
        self.pre_pago = pre_pago
        self.tree_process = {}


    def get_params(self, session):
        # O método session.prompt é utilizado para coletar entradas do usuário de forma interativa
        # Importante para que os prints não sejam encima antes do prompt
        self.limit_cpu = float(session.prompt("Limite de CPU do processo (s): "))
        self.limit_mem = float(session.prompt("Limite de memória do processo (MB): "))
        self.limit_time = float(session.prompt("Limite de tempo (s): "))

    def launch_process(self, command):
        # O método subprocess.Popen é utilizado para iniciar um novo processo
        # O método Popen é uma maneira de executar um comando no sistema operacional
        # psutil.Process é utilizado para obter informações sobre o processo
        process = subprocess.Popen(command)
        self.process = psutil.Process(process.pid)
        self.tree_process[self.process.pid] = {}

    def get_cpu_time(self):
        # O método cpu_times() retorna o tempo de CPU utilizado pelo processo
        cpu_times = self.process.cpu_times()
        return cpu_times.user + cpu_times.system

    def get_childrens(self, process: psutil.Process):
        # O método get_childrens() cria a arvore de processos com os filhos dos processos pai
        try:
            childrens = process.children(recursive=False) 
            active_childrens = {}
            if childrens:
                for child in childrens:
                    cpu_times = child.cpu_times()
                    cpu_time = cpu_times.user + cpu_times.system
                    ram_usage = child.memory_info().rss     
                    active_childrens[child.pid] = {
                        "status": child.status(),
                        "cpu_time": cpu_time,  
                        "ram": ram_usage / (1024 * 1024)  
                    }
                self.tree_process[process.pid] = active_childrens
            else:
                return 
        except:
            pass
        
            

    def get_memory_usage(self):
        # O método memory_info() retorna informações sobre o uso de memória do processo
        return self.process.memory_info().rss / (1024 * 1024)

    def monitor_loop(self):
        # O método time.time() retorna o tempo atual em segundos desde a época (epoch)
        start_time = time.time()
        self.proc_cpu_time = self.get_cpu_time()

        try:
            while self.process.is_running():
                wall_clock = time.time() - start_time
                cpu_total = self.get_cpu_time()
                cpu_time_calc = cpu_total - self.proc_cpu_time
                self.proc_cpu_time = cpu_total
                # O método memory_info() retorna informações sobre o uso de memória do processo
                mem_rss_mb = self.get_memory_usage()
                self.get_childrens(self.process)

                if self.pre_pago:
                    # Débito direto no saldo pré-pago
                    if not CreditManagerPrePago.debit(cpu_time_calc):
                        print(
                            f"\n[{self.process.pid}] Créditos esgotados. Encerrando processo."
                        )
                        self.process.terminate()
                        break
                else:
                    # Pós-pago acumula cpu usada
                    with FMS.total_cpu_lock:
                        FMS.total_cpu_used += cpu_time_calc

                # Verifica se o tempo de execução, uso de CPU ou memória excedeu os limites
                if wall_clock > self.limit_time:
                    print(f"\n[{self.process.pid}] Tempo excedido.")
                    self.process.terminate()
                    break

                # Verifica se o tempo de CPU individual excedeu o limite
                if cpu_total > self.limit_cpu:
                    print(f"\n[{self.process.pid}] CPU individual excedida.")
                    self.process.terminate()
                    break

                # Verifica se o total de RAM do processo excedeu o limite
                if mem_rss_mb > self.limit_mem:
                    print(f"\n[{self.process.pid}] Memória excedida.")
                    self.process.terminate()
                    break

                # Sleep para fazer a verificação a cada 0.5 segundos
                time.sleep(0.5)

        # Printa as informações do processo após o término
        finally:
            self.process.wait()
            print(f"\n[{self.process.pid}] Processo encerrado.")
            print(
                f"[{self.process.pid}] T: {wall_clock:.1f}s | CPU: {cpu_total:.2f}s | "
                f"RAM: {mem_rss_mb:.2f} MB"
            )
            for key in self.tree_process:
                for element in self.tree_process[key]:
                    print(f"  ﹂[{element}] T: {wall_clock:.1f}s | CPU: {self.tree_process[key][element]['cpu_time']:.2f}s |"
                          f" RAM: {self.tree_process[key][element]['ram']:.2f} MB"                         
                          )
            if self.pre_pago:
                print(f"Créditos restantes: R${CreditManagerPrePago.get_balance():.2f}")

    # Inicia o processo e a thread de monitoramento
    # O método threading.Thread é utilizado para criar uma nova thread
    # O parâmetro daemon=True indica que a thread deve ser encerrada quando o programa principal terminar e rodar em segundo plano
    def start_process_in_thread(self, command):
        self.launch_process(command)
        thread = threading.Thread(target=self.monitor_loop, daemon=True)
        thread.start()


if __name__ == "__main__":
    print("=== FMS MULTI ===")
    # Instancia o PromptSession para coletar entradas do usuário
    # O PromptSession é uma classe do prompt_toolkit que fornece uma interface para criar sessões de prompt interativas
    session = PromptSession()

    # O método patch_stdout() é utilizado para garantir que a saída padrão seja exibida corretamente
    # Isso é importante para evitar que a saída do programa seja misturada com o prompt
    with patch_stdout():
        modo = session.prompt("Escolha modo (pre-pago / pos-pago): ").strip().lower()
        if modo not in ("pre-pago", "pos-pago"):
            print("Modo inválido. Saindo.")
            exit()

        # Se o modo for pré-pago, solicita o valor inicial de créditos
        if modo == "pre-pago":
            try:
                CreditManagerPrePago.set_total(
                    float(session.prompt("Créditos de CPU disponíveis (s): R$"))
                )
            except ValueError:
                print("Valor inválido. Encerrando.")
                exit()

        # O loop principal do programa
        # O loop while True é utilizado para manter o programa em execução até que o usuário decida sair
        while True:
            try:
                caminho = session.prompt("\nCaminho do binário (ou 'sair'): ").strip()
                if caminho.lower() == "sair":
                    break

                fms = FMS(pre_pago=(modo == "pre-pago"))
                fms.get_params(session)
                command = caminho.split()
                fms.start_process_in_thread(command)

            except ValueError:
                print("Entrada inválida. Tente novamente.")
            except KeyboardInterrupt:
                print("\nEncerrando...")
                break
        
        # Se o modo for pós-pago, cobra o total de CPU usado
        if modo == "pos-pago":
            # Ao sair, cobrar o total de CPU usado
            total_usado = FMS.total_cpu_used
            print(f"\nTotal de CPU usado: {total_usado:.2f} segundos.")

            while True:
                try:
                    pago = float(session.prompt("Digite o valor para pagar: R$"))
                    if pago < total_usado:
                        print("Valor insuficiente, digite o valor correto.")
                    elif pago > total_usado:
                        print("Obrigado por pagar a mais, troxa! :)")
                        break
                    else:
                        print("Pagamento confirmado. Obrigado!")
                        break
                except ValueError:
                    print("Valor inválido, tente novamente.")
