"""
configurar_token.py

Programa de configuração inicial - roda separado do monitor.py e serve só
para salvar o token da API do Tiny (de uma conta específica) com segurança
no Gerenciador de Credenciais do Windows deste computador. Precisa ser
rodado uma vez POR CONTA/CNPJ cadastrado no robô, em cada computador novo,
antes de usar o RoboEtiquetas.exe.
"""

from tiny_api import salvar_token, CONTAS

print("=== Configuração do RoboEtiquetas ===\n")

if len(CONTAS) == 1:
    nome_conta = CONTAS[0]
else:
    print("Contas cadastradas no robô:")
    for i, nome in enumerate(CONTAS, start=1):
        print(f"  {i}. {nome}")
    print()

    escolha = input(f"Qual conta você quer configurar? (1-{len(CONTAS)}): ").strip()
    try:
        nome_conta = CONTAS[int(escolha) - 1]
    except (ValueError, IndexError):
        print("\nOpção inválida. Nada foi salvo.")
        input("\nPressione Enter para sair...")
        raise SystemExit(1)

print(f"\nConfigurando a conta '{nome_conta}'.")
print("Cole abaixo o token da API 2.0 do Tiny dessa conta (Ferramentas > Preferências > API).\n")

token = input("Token: ").strip()

if not token:
    print("\nNenhum token digitado. Nada foi salvo.")
else:
    salvar_token(token, nome_conta=nome_conta)
    print(f"\nToken da conta '{nome_conta}' salvo com sucesso neste computador!")
    if len(CONTAS) > 1:
        print("Se ainda faltar configurar outra conta, rode este programa de novo.")
    print("Agora você já pode rodar o RoboEtiquetas.exe normalmente.")

input("\nPressione Enter para sair...")
