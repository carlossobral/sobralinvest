import os

# Extensões de arquivos que queremos mapear
EXTENSOES_PERMITIDAS = {'.py', '.sql', '.toml', '.md', '.txt', '.yaml', '.yml'}
# Pastas que devemos ignorar completamente para o arquivo não ficar gigante
PASTAS_IGNORADAS = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'build', 'dist', '.github'}

def consolidar_repositorio(output_file="todo_o_projeto.txt"):
    print("Iniciando a leitura do repositório...")
    contador = 0
    with open(output_file, "w", encoding="utf-8") as f_out:
        for raiz, diretorios, arquivos in os.walk("."):
            # Modifica os diretórios in-place para ignorar as pastas restritas
            diretorios[:] = [d for d in diretorios if d not in PASTAS_IGNORADAS]
            
            for arquivo in arquivos:
                nome_ext = os.path.splitext(arquivo)[1].lower()
                if nome_ext in EXTENSOES_PERMITIDAS and arquivo != "juntar_codigo.py" and arquivo != output_file:
                    caminho_completo = os.path.join(raiz, arquivo)
                    
                    f_out.write(f"\n{'='*80}\n")
                    f_out.write(f" ARQUIVO: {caminho_completo}\n")
                    f_out.write(f"{'='*80}\n\n")
                    
                    try:
                        with open(caminho_completo, "r", encoding="utf-8") as f_in:
                            f_out.write(f_in.read())
                        contador += 1
                    except Exception as e:
                        f_out.write(f"// Erro ao ler arquivo: {str(e)}\n")
                    f_out.write("\n")
                    
    print(f"Pronto! {contador} arquivos consolidados com sucesso em: {output_file}")

if __name__ == "__main__":
    consolidar_repositorio()
