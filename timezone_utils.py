"""
Módulo central de controle de data, hora e fuso horário do Facilita.

Garante que todas as operações, logs de auditoria, comprovantes, relatórios
e cálculos de vencimento/atraso utilizem rigorosamente o horário oficial
de Fortaleza/CE/Brasil (UTC-3), prevenindo cobranças indevidas ou registros
com horários adiantados decorrentes de servidores em UTC (nuvem/Vercel).
"""
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


def _obter_fuso_horario():
    nome_fuso = os.getenv("APP_TIMEZONE", "America/Fortaleza").strip() or "America/Fortaleza"
    try:
        return ZoneInfo(nome_fuso)
    except Exception:
        # Fallback seguro para UTC-3 (Horário Padrão de Brasília / Fortaleza)
        return timezone(timedelta(hours=-3))


APP_TIMEZONE = _obter_fuso_horario()
FUSO_BRASIL_FIXO = timezone(timedelta(hours=-3))


def agora_brasil() -> datetime:
    """Retorna o datetime atual no fuso horário de Fortaleza/CE (UTC-3)."""
    return datetime.now(APP_TIMEZONE)


def hoje_brasil() -> date:
    """Retorna a data atual correta no fuso horário de Fortaleza/CE (UTC-3)."""
    return agora_brasil().date()


def iso_agora_brasil() -> str:
    """Retorna timestamp formatado para armazenamento seguro com indicação de timezone."""
    return agora_brasil().isoformat(sep=" ", timespec="seconds")


def to_brasil(value: Any) -> datetime | date | None:
    """
    Converte qualquer valor de data/hora para o fuso de Fortaleza/CE (UTC-3).

    Suporta:
    - datetime (aware ou naive, onde naive é tratado como UTC do servidor/banco)
    - date pura (retornada inalterada para preservar vencimentos e competências)
    - strings ISO com timezone (+00, Z, -03:00, etc.)
    - strings legadas de bancos (CURRENT_TIMESTAMP do SQLite ou PostgreSQL)
    """
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(APP_TIMEZONE)
        # Se ingênuo (naive), assume que se originou em UTC do servidor/banco
        return value.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE)

    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    # Se for uma data pura (formato YYYY-MM-DD), preserva a data sem deslocamento de hora
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text)
        except ValueError:
            return text

    # Trata formato ISO com sufixo Z
    clean_text = text.replace("Z", "+00:00")

    try:
        dt = datetime.fromisoformat(clean_text)
        if dt.tzinfo is not None:
            return dt.astimezone(APP_TIMEZONE)
        # Sem timezone explícito na string (ex: "2026-09-20 04:04:01" gerada por CURRENT_TIMESTAMP do SQLite):
        # como o banco gera em UTC, interpretamos como UTC e convertemos para horário de Fortaleza
        return dt.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE)
    except Exception:
        pass

    # Fallback para regex de data e hora se fromisoformat não conseguir ler
    m = re.match(
        r"^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?([+-]\d{2}:?\d{2}|Z)?$",
        text,
    )
    if m:
        try:
            ano, mes, dia = int(m.group(1)), int(m.group(2)), int(m.group(3))
            h, mi, s = int(m.group(4)), int(m.group(5)), int(m.group(6))
            tz_str = m.group(7)
            if tz_str:
                tz_clean = tz_str.replace("Z", "+00:00")
                if len(tz_clean) == 3:  # ex: +00
                    tz_clean += ":00"
                offset_dt = datetime.fromisoformat(f"{ano:04d}-{mes:02d}-{dia:02d}T{h:02d}:{mi:02d}:{s:02d}{tz_clean}")
                return offset_dt.astimezone(APP_TIMEZONE)
            else:
                return datetime(ano, mes, dia, h, mi, s, tzinfo=timezone.utc).astimezone(APP_TIMEZONE)
        except Exception:
            pass

    return text


def format_time_br(value: Any) -> str:
    """Extrai o horário HH:MM:SS formatado no fuso horário do Brasil (Fortaleza/CE)."""
    if value is None or value == "":
        return ""

    convertido = to_brasil(value)
    if isinstance(convertido, datetime):
        return convertido.strftime("%H:%M:%S")

    # Fallback de segurança para texto cru
    text = str(value).strip()
    m = re.search(r"(\d{2}):(\d{2}):(\d{2})", text)
    if m:
        return f"{m.group(1)}:{m.group(2)}:{m.group(3)}"
    return ""


def format_date_br(value: Any) -> str:
    """
    Formata datas para dd/mm/aaaa no fuso horário de Fortaleza/CE.

    Se o valor contiver hora (datetime ou timestamp), converte para o horário local
    antes de extrair a data, evitando saltos de data após 21h em servidores UTC.
    """
    if value is None or value == "":
        return "-"

    convertido = to_brasil(value)
    if isinstance(convertido, (datetime, date)):
        return convertido.strftime("%d/%m/%Y")

    text = str(value).strip()
    if not text:
        return "-"

    try:
        return date.fromisoformat(text[:10]).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return text


def format_datetime_br(value: Any) -> str:
    """Formata data e hora para dd/mm/aaaa HH:MM:SS no fuso horário de Fortaleza/CE."""
    if value is None or value == "":
        return "-"

    convertido = to_brasil(value)
    if isinstance(convertido, datetime):
        return convertido.strftime("%d/%m/%Y %H:%M:%S")

    if isinstance(convertido, date):
        return convertido.strftime("%d/%m/%Y 00:00:00")

    return str(value)
