"""
Script de backup do banco de dados PostgreSQL.

Uso:
    python -m scripts.backup [--output <diretório>]

Exemplo:
    python -m scripts.backup --output /backups

Executa pg_dump no container postgres e salva em arquivo com timestamp.
Pode ser agendado via cron dentro do container ou host.
"""

import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bot.core.config import settings


def backup_database(output_dir: str = "/backups") -> Optional[Path]:
    """
    Realiza backup do PostgreSQL usando pg_dump.

    Args:
        output_dir: Diretório onde salvar o arquivo.

    Returns:
        Path: Caminho do arquivo de backup, ou None se falhar.
    """
    # Cria diretório se não existir
    backup_dir = Path(output_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{settings.POSTGRES_DB}_{timestamp}.sql"
    filepath = backup_dir / filename

    # Comando pg_dump executado dentro do container postgres
    cmd = [
        "docker", "exec", "larizinha_postgres",
        "pg_dump",
        "-U", settings.POSTGRES_USER,
        "-d", settings.POSTGRES_DB,
        "--clean",
        "--if-exists",
    ]

    try:
        with open(filepath, "w") as f:
            result = subprocess.run(
                cmd,
                stdout=f,
                stderr=subprocess.PIPE,
                check=True,
                text=True,
            )
        print(f"✅ Backup realizado: {filepath}")
        return filepath
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro no backup: {e.stderr}")
        return None


def main():
    """Executa o script."""
    output_dir = "/backups"
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_dir = sys.argv[idx + 1]

    backup_database(output_dir)


if __name__ == "__main__":
    main()
