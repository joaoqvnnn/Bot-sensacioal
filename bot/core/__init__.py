"""
Núcleo do bot.

Contém configurações, conexões de banco, Redis, logging e utilitários centrais.
Este módulo não deve importar nada pesado para evitar efeitos colaterais na inicialização.
"""

# Não importe módulos aqui para evitar imports circulares.
# Os módulos devem ser importados explicitamente onde forem necessários.
