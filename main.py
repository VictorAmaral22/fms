#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import time
import psutil
import threading
import os
import shlex

class FMS:
    def __init__(self):
        self.total_fms_cpu_quota_seconds = 0.0
        self.fms_cpu_time_consumed_seconds = 0.0
        self.fms_active = True
        self.prepaid_mode = False
        self.postpaid_mode = False
        self.credit_amount = 0.0
        self.cost_per_second = 1.0  # $1 per second
        self.total_bill = 0.0

    def _get_float_input(self, prompt, allow_empty=False, positive_only=True):
        """Helper para obter entrada float válida."""
        while True:
            try:
                val_str = input(prompt)
                if allow_empty and not val_str:
                    return None
                val = float(val_str)
                if positive_only and val <= 0:
                    print("O valor deve ser positivo.")
                else:
                    return val
            except ValueError:
                print("Entrada inválida. Por favor, insira um número.")

    def _get_operation_mode(self):
        """Permite ao usuário escolher entre modo quota, pré-pago ou pós-pago."""
        print("\n=== Escolha do Modo de Operação ===")
        print("1. Modo Quota (definir tempo total de CPU)")
        print("2. Modo Pré-pago ($1 por segundo de CPU)")
        print("3. Modo Pós-pago (pague pelo uso, $1.20 por segundo)")
        
        while True:
            choice = input("Escolha o modo (1, 2 ou 3): ").strip()
            if choice == "1":
                self.prepaid_mode = False
                self.postpaid_mode = False
                return
            elif choice == "2":
                self.prepaid_mode = True
                self.postpaid_mode = False
                self.cost_per_second = 1.0
                return
            elif choice == "3":
                self.prepaid_mode = False
                self.postpaid_mode = True
                self.cost_per_second = 1.20  # Taxa mais alta para pós-pago
                self.total_fms_cpu_quota_seconds = float('inf')  # Sem limite predefinido
                return
            print("Opção inválida. Por favor, escolha 1, 2 ou 3.")

    def _get_prepaid_credits(self):
        """Gerencia a compra de créditos no modo pré-pago."""
        print("\n=== Modo Pré-pago ===")
        print("Cada segundo de CPU custa $1")
        while True:
            try:
                amount = float(input("Quanto deseja pagar ($)? "))
                if amount <= 0:
                    print("O valor deve ser positivo.")
                    continue
                self.credit_amount = amount
                self.total_fms_cpu_quota_seconds = amount  # 1:1 ratio
                print(f"\nCrédito adquirido: ${amount:.2f}")
                print(f"Tempo de CPU disponível: {amount:.2f} segundos")
                return
            except ValueError:
                print("Por favor, insira um valor numérico válido.")

    def _get_user_inputs_for_fms_config(self):
        """Consulta o usuário para a configuração inicial do FMS."""
        print("--- Configuração Inicial do FMS ---")
        self._get_operation_mode()
        
        if self.prepaid_mode:
            self._get_prepaid_credits()
        else:
            self.total_fms_cpu_quota_seconds = self._get_float_input(
                "Informe a quota TOTAL de tempo de CPU para o FMS (segundos, ex: 600): "
            )
        print("------------------------------------")

    def _terminate_process(self, ps_process: psutil.Process, reason: str):
        """Tenta terminar um processo de forma graciosa e depois força, se necessário."""
        pid = ps_process.pid
        print(f"[{pid}] Encerrando processo: {reason}")
        try:
            ps_process.terminate()  # Envia SIGTERM
            ps_process.wait(timeout=0.5)  # Espera um pouco para terminar
        except psutil.TimeoutExpired:
            print(f"[{pid}] Processo não terminou com SIGTERM, enviando SIGKILL.")
            ps_process.kill()  # Envia SIGKILL
        except psutil.NoSuchProcess:
            print(f"[{pid}] Processo já terminou (NoSuchProcess) durante a tentativa de encerramento.")
        except Exception as e:
            print(f"[{pid}] Erro inesperado ao tentar encerrar o processo: {e}")

    def _monitor_process_thread_func(self, ps_process: psutil.Process,
                                      process_cpu_limit_seconds, process_memory_limit_bytes, process_timeout_seconds,
                                      stop_event: threading.Event, result_dict: dict):
        """
        Thread que monitora um processo em execução.
        Popula `result_dict` com os resultados.
        """
        pid = ps_process.pid
        result_dict.update({
            'pid': pid,
            'status': 'running',
            'reason': '',
            'cpu_time_used_seconds': 0.0,
            'max_memory_rss_bytes': 0,
            'wall_time_elapsed_seconds': 0.0,
            'terminate_fms_due_to_memory': False,
            'children_pids': [] # Não está sendo usado, mas mantido para consistência
        })

        start_time_monotonic = time.monotonic()
        initial_cpu_times = None
        try:
            initial_cpu_times = ps_process.cpu_times()
        except psutil.Error:
            result_dict['status'] = 'terminated_early'
            result_dict['reason'] = 'Processo terminou antes do início do monitoramento detalhado.'
            return

        monitoring_interval_seconds = 1.0

        print(f"[{pid}] Iniciando monitoramento. Limites: CPU {process_cpu_limit_seconds or 'N/A'}s, "
              f"Mem {process_memory_limit_bytes/(1024*1024) if process_memory_limit_bytes else 'N/A'}MB, "
              f"Timeout {process_timeout_seconds or 'N/A'}s")

        try:
            while ps_process.is_running() and not stop_event.is_set():
                current_monotonic_time = time.monotonic()
                result_dict['wall_time_elapsed_seconds'] = current_monotonic_time - start_time_monotonic

                # Coleta de métricas (CPU e Memória)
                current_cpu_times = None
                current_memory_rss_bytes = 0

                try:
                    current_cpu_times = ps_process.cpu_times()
                    mem_info = ps_process.memory_info()
                    current_memory_rss_bytes = mem_info.rss
                except psutil.NoSuchProcess:
                    break # Processo terminou, sair do loop de monitoramento
                except psutil.AccessDenied:
                    print(f"[{pid}] Acesso negado ao coletar métricas. O monitoramento pode ser limitado.")
                except Exception as e:
                    print(f"[{pid}] Erro ao coletar métricas: {e}")

                # Atualizar CPU time usado pelo processo
                if initial_cpu_times and current_cpu_times:
                    result_dict['cpu_time_used_seconds'] = \
                        (current_cpu_times.user - initial_cpu_times.user) + \
                        (current_cpu_times.system - initial_cpu_times.system)

                # Atualizar pico de memória
                if current_memory_rss_bytes > result_dict['max_memory_rss_bytes']:
                    result_dict['max_memory_rss_bytes'] = current_memory_rss_bytes
                
                # Relatório de Progresso
                print(f"[{pid}] Progresso: CPU: {result_dict['cpu_time_used_seconds']:.2f}s, "
                      f"Mem RSS: {result_dict['max_memory_rss_bytes']/(1024*1024):.2f}MB, "
                      f"Wall: {result_dict['wall_time_elapsed_seconds']:.1f}s")

                # Checks for termination conditions, moved to individual functions for clarity
                if self._check_and_act_on_timeout(ps_process, process_timeout_seconds, result_dict): return
                if self._check_and_act_on_memory_limit(ps_process, process_memory_limit_bytes, result_dict): return
                if self._check_and_act_on_process_cpu_limit(ps_process, process_cpu_limit_seconds, result_dict): return
                if self._check_and_act_on_fms_global_cpu_imminent(ps_process, result_dict): return

                time.sleep(monitoring_interval_seconds)

            # If loop exited, process either finished or was signaled to stop
            if result_dict['status'] == 'running':
                result_dict['status'] = 'completed'

        except psutil.NoSuchProcess:
            result_dict['status'] = 'terminated_unexpectedly'
            result_dict['reason'] = 'Processo terminou inesperadamente durante o monitoramento.'
        except Exception as e:
            print(f"[{pid}] Erro crítico no thread de monitoramento: {e}")
            result_dict['status'] = 'monitoring_error'
            result_dict['reason'] = f'Erro no monitoramento: {str(e)}'
        finally:
            # Ensure final wall time is recorded
            if result_dict['wall_time_elapsed_seconds'] == 0.0:
                result_dict['wall_time_elapsed_seconds'] = time.monotonic() - start_time_monotonic
            
            # Try to get final CPU time if process completed normally
            if result_dict['status'] == 'completed' and initial_cpu_times:
                try:
                    final_cpu_times = ps_process.cpu_times()
                    result_dict['cpu_time_used_seconds'] = \
                        (final_cpu_times.user - initial_cpu_times.user) + \
                        (final_cpu_times.system - initial_cpu_times.system)
                except psutil.Error:
                    pass

            print(f"[{pid}] Monitoramento encerrado. Status final: {result_dict['status']}. Razão: {result_dict['reason']}")

    def _check_and_act_on_timeout(self, ps_process, limit_seconds, result_dict):
        """Verifica e atua no limite de tempo de relógio (timeout) do processo."""
        if limit_seconds is not None and result_dict['wall_time_elapsed_seconds'] > limit_seconds:
            print(f"[{ps_process.pid}] Timeout de {limit_seconds}s atingido.")
            result_dict['status'] = 'timeout'
            result_dict['reason'] = f"Timeout de {limit_seconds}s."
            self._terminate_process(ps_process, "Timeout atingido.")
            return True
        return False

    def _check_and_act_on_memory_limit(self, ps_process, limit_bytes, result_dict):
        """Verifica e atua no limite de memória do processo."""
        if limit_bytes is not None and result_dict['max_memory_rss_bytes'] > limit_bytes:
            print(f"[{ps_process.pid}] Limite de memória ({limit_bytes/(1024*1024):.2f}MB) excedido "
                  f"(usou {result_dict['max_memory_rss_bytes']/(1024*1024):.2f}MB).")
            result_dict['status'] = 'memory_exceeded'
            result_dict['reason'] = f"Limite de memória ({limit_bytes/(1024*1024):.2f}MB) excedido."
            result_dict['terminate_fms_due_to_memory'] = True
            self._terminate_process(ps_process, "Limite de memória excedido.")
            return True
        return False

    def _check_and_act_on_process_cpu_limit(self, ps_process, limit_seconds, result_dict):
        """Verifica e atua na quota de CPU individual do processo."""
        if limit_seconds is not None and result_dict['cpu_time_used_seconds'] > limit_seconds:
            print(f"[{ps_process.pid}] Quota de CPU do processo ({limit_seconds}s) excedida "
                  f"(usou {result_dict['cpu_time_used_seconds']:.2f}s).")
            result_dict['status'] = 'cpu_exceeded_process'
            result_dict['reason'] = f"Quota de CPU do processo ({limit_seconds}s) excedida."
            self._terminate_process(ps_process, "Quota de CPU do processo excedida.")
            return True
        return False

    def _check_and_act_on_fms_global_cpu_imminent(self, ps_process, result_dict):
        """Verifica se a quota global de CPU do FMS está prestes a ser excedida."""
        estimated_fms_consumption = self.fms_cpu_time_consumed_seconds + result_dict['cpu_time_used_seconds']
        if estimated_fms_consumption > self.total_fms_cpu_quota_seconds:
            print(f"[{ps_process.pid}] ATENÇÃO: Quota total de CPU do FMS ({self.total_fms_cpu_quota_seconds}s) está prestes a ser excedida "
                  f"(consumo FMS: {self.fms_cpu_time_consumed_seconds:.2f}s + atual: {result_dict['cpu_time_used_seconds']:.2f}s).")
            result_dict['status'] = 'fms_cpu_quota_imminent'
            result_dict['reason'] = "Processo encerrado para evitar estouro da quota total do FMS."
            self._terminate_process(ps_process, "Quota total de CPU do FMS iminente.")
            return True
        return False

    def _update_prepaid_status(self):
        """Atualiza e mostra o status dos créditos no modo pré-pago."""
        remaining_credit = self.total_fms_cpu_quota_seconds - self.fms_cpu_time_consumed_seconds
        print("\n=== Status do Crédito ===")
        print(f"Crédito inicial: ${self.credit_amount:.2f}")
        print(f"CPU consumida: ${self.fms_cpu_time_consumed_seconds:.2f}")
        print(f"Crédito restante: ${remaining_credit:.2f}")
        print(f"Tempo de CPU restante: {remaining_credit:.2f} segundos")
        print("=======================")

    def _update_postpaid_status(self):
        """Atualiza e mostra o status da conta no modo pós-pago."""
        self.total_bill = self.fms_cpu_time_consumed_seconds * self.cost_per_second
        print("\n=== Status do Consumo (Pós-pago) ===")
        print(f"Tempo CPU usado: {self.fms_cpu_time_consumed_seconds:.2f}s")
        print(f"Custo atual: ${self.total_bill:.2f} (${self.cost_per_second:.2f}/s)")
        print("================================")

    def _get_program_execution_params(self):
        """Obtém parâmetros para execução de um novo programa."""
        print("\n--- Novo Programa para Execução ---")
        binary_input = input("Programa e args (ou 'sair' para encerrar): ").strip()

        if not binary_input:
            print("Nenhum comando fornecido.")
            return None, None, None, None, False

        if binary_input.lower() == 'sair':
            return None, None, None, None, True

        try:
            # Usar shlex.split para lidar corretamente com argumentos que contêm espaços
            command_parts = shlex.split(binary_input)
            binary_path = command_parts[0]
            args = command_parts[1:] if len(command_parts) > 1 else []
        except Exception as e:
            print(f"Erro ao processar o comando: {e}")
            return None, None, None, None, False

        # Obter limites de recursos
        cpu_limit = self._get_float_input(
            "Quota CPU para programa (segundos, Enter=sem limite): ",
            allow_empty=True
        )

        timeout = self._get_float_input(
            "Timeout para programa (segundos, Enter=sem limite): ",
            allow_empty=True
        )

        memory_limit_mb = self._get_float_input(
            "Limite de memória (MB, Enter=sem limite): ",
            allow_empty=True
        )

        # Converter limite de memória de MB para bytes se especificado
        memory_limit_bytes = None
        if memory_limit_mb is not None:
            memory_limit_bytes = int(memory_limit_mb * 1024 * 1024)

        print("------------------------------------------------")
        return (binary_path, args), cpu_limit, timeout, memory_limit_bytes, False

    def run(self):
        """Método principal que executa o FMS."""
        self._get_user_inputs_for_fms_config()
        mode_str = "pós-pago" if self.postpaid_mode else "pré-pago" if self.prepaid_mode else "quota"
        print(f"\nFMS iniciado em modo {mode_str}.")
        
        if self.postpaid_mode:
            print(f"Taxa: ${self.cost_per_second:.2f}/segundo")
            print("ATENÇÃO: Você será cobrado pelo tempo de CPU utilizado!")
        
        try:
            while self.fms_active:
                if self.postpaid_mode:
                    self._update_postpaid_status()
                elif self.prepaid_mode:
                    self._update_prepaid_status()
                else:
                    print(f"\nQuota de CPU restante: "
                          f"{(self.total_fms_cpu_quota_seconds - self.fms_cpu_time_consumed_seconds):.2f}s")

                command, proc_cpu_limit, proc_timeout, proc_mem_limit_bytes, should_exit = \
                    self._get_program_execution_params()

                if should_exit:
                    break
                if command is None:
                    continue
                
                binary_path, args = command
                launched_process_popen = None
                launched_process_psutil = None
                launch_failed = False

                try:
                    full_command_str = binary_path + (' ' + ' '.join(args) if args else '')
                    print(f"\nTentando executar: '{full_command_str}'")
                    launched_process_popen = subprocess.Popen([binary_path] + args, 
                                                              stdout=subprocess.PIPE, 
                                                              stderr=subprocess.PIPE)
                    launched_process_psutil = psutil.Process(launched_process_popen.pid)
                    print(f"Processo {launched_process_popen.pid} lançado para executar '{full_command_str}'.")

                except FileNotFoundError:
                    print(f"Erro: O programa '{binary_path}' não foi encontrado.")
                    launch_failed = True
                except PermissionError:
                    print(f"Erro: Sem permissão para executar '{binary_path}'.")
                    launch_failed = True
                except Exception as e:
                    print(f"Erro ao lançar '{binary_path}': {e}")
                    launch_failed = True

                if launch_failed:
                    print("Lançamento falhou. Não será descontado da quota do FMS.")
                    continue

                monitoring_results = {}
                stop_monitoring_event = threading.Event()

                monitor_thread = threading.Thread(
                    target=self._monitor_process_thread_func,
                    args=(launched_process_psutil, proc_cpu_limit, proc_mem_limit_bytes,
                          proc_timeout, stop_monitoring_event, monitoring_results)
                )
                monitor_thread.start()

                try:
                    launched_process_popen.wait() 
                except Exception as e:
                    print(f"Erro ao esperar pelo processo Popen {launched_process_popen.pid}: {e}")
                    if launched_process_psutil and launched_process_psutil.is_running():
                        print(f"Processo {launched_process_psutil.pid} ainda está rodando. Tentando terminar...")
                        self._terminate_process(launched_process_psutil, "Erro ao esperar, encerrando.")
                finally:
                    stop_monitoring_event.set()
                    monitor_thread.join(timeout=5.0)
                    if monitor_thread.is_alive():
                        print(f"Atenção: Thread de monitoramento para PID {launched_process_psutil.pid} não encerrou no tempo esperado.")

                pid_res = monitoring_results.get('pid', launched_process_psutil.pid if launched_process_psutil else 'N/A')
                status_res = monitoring_results.get('status', 'unknown_after_wait')
                reason_res = monitoring_results.get('reason', 'Processo Popen terminou, mas detalhes da thread de monitoramento podem estar incompletos.')
                cpu_used_res = monitoring_results.get('cpu_time_used_seconds', 0.0)
                mem_used_res_bytes = monitoring_results.get('max_memory_rss_bytes', 0)
                wall_time_res = monitoring_results.get('wall_time_elapsed_seconds', 0.0)

                print(f"\n--- Relatório de Execução para '{binary_path}' (PID: {pid_res}) ---")
                print(f"Status Final: {status_res.upper()}")
                if reason_res: print(f"Detalhes: {reason_res}")
                print(f"Código de Saída do Processo: {launched_process_popen.returncode if launched_process_popen else 'N/A (processo não foi lançado ou erro de execução)'}")
                print(f"Tempo de CPU (user+system) utilizado: {cpu_used_res:.2f} segundos.")
                print(f"Pico de memória RSS utilizado: {mem_used_res_bytes / (1024*1024):.2f} MB.")
                print(f"Tempo de relógio (wall time) decorrido: {wall_time_res:.2f} segundos.")
                print("----------------------------------------------------------")

                self.fms_cpu_time_consumed_seconds += cpu_used_res

                if monitoring_results.get('terminate_fms_due_to_memory', False):
                    print("\nFMS ENCERRANDO: Um programa monitorado excedeu seu limite de memória.")
                    self.fms_active = False
                elif self.fms_cpu_time_consumed_seconds >= self.total_fms_cpu_quota_seconds:
                    print(f"\nFMS ENCERRANDO: Quota total de CPU do FMS ({self.total_fms_cpu_quota_seconds:.2f}s) esgotada ou excedida.")
                    print(f"Total consumido: {self.fms_cpu_time_consumed_seconds:.2f}s.")
                    self.fms_active = False
            
        except KeyboardInterrupt:
            print("\nFMS interrompido (Ctrl+C).")
        finally:
            if self.postpaid_mode:
                # Atualizar bill final antes de mostrar
                self.total_bill = self.fms_cpu_time_consumed_seconds * self.cost_per_second
                print("\n=== Fatura Final ===")
                print(f"Tempo total CPU: {self.fms_cpu_time_consumed_seconds:.2f}s")
                print(f"Valor total devido: ${self.total_bill:.2f} (${self.cost_per_second:.2f}/s)")
                print("==================")
            print("\n--- FMS Finalizado ---")
            print(f"Tempo total de CPU consumido por todos os programas gerenciados: {self.fms_cpu_time_consumed_seconds:.2f}s")
            print(f"Quota total de CPU do FMS definida: {self.total_fms_cpu_quota_seconds:.2f}s")

if __name__ == '__main__':
    fms_system = FMS()
    try:
        fms_system.run()
    except KeyboardInterrupt:
        print("\nFMS interrompido pelo usuário (Ctrl+C).")
    except Exception as e:
        print(f"\nERRO INESPERADO NO FMS: {e}")
    finally:
        print("Encerrando FMS.")