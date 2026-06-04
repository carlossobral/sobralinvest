import json

with open("petr4_dividendos.json") as f:
    dados = json.load(f)

eventos = dados["dividends"]

vistos = set()
duplicados = []

for d in eventos:
    chave = (
        d["date"],
        d["type"],
        d["value"]
    )

    if chave in vistos:
        duplicados.append(chave)

    vistos.add(chave)

print(f"Total eventos: {len(eventos)}")
print(f"Duplicados: {len(duplicados)}")

for d in duplicados:
    print(d)
