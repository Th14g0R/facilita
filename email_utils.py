"""
Módulo de envio de e-mails transacionais e utilitários de comunicação do Facilita.

Suporta servidores SMTP convencionais (Gmail, Mailgun, Amazon SES, SendGrid, etc.)
configuráveis via variáveis de ambiente, com fallback seguro para ambientes onde
o serviço de e-mail ainda não foi configurado.
"""
from __future__ import annotations

import logging
import os
import re
import smtplib
from email.message import EmailMessage
from typing import Any

logger = logging.getLogger(__name__)


def obter_config_smtp() -> dict[str, Any]:
    """Retorna as configurações de SMTP a partir de variáveis de ambiente."""
    host = (
        os.getenv("SMTP_HOST")
        or os.getenv("SMTP_SERVER")
        or os.getenv("MAIL_SERVER")
        or ""
    ).strip()

    port_str = (
        os.getenv("SMTP_PORT")
        or os.getenv("MAIL_PORT")
        or "587"
    ).strip()
    try:
        port = int(port_str)
    except ValueError:
        port = 587

    user = (
        os.getenv("SMTP_USER")
        or os.getenv("MAIL_USERNAME")
        or ""
    ).strip()

    password = (
        os.getenv("SMTP_PASSWORD")
        or os.getenv("SMTP_PASS")
        or os.getenv("MAIL_PASSWORD")
        or ""
    ).strip()

    # Define uso de SSL ou TLS
    use_ssl_env = os.getenv("SMTP_USE_SSL") or os.getenv("MAIL_USE_SSL")
    if use_ssl_env is not None:
        use_ssl = use_ssl_env.lower() in ("1", "true", "yes", "on")
    else:
        use_ssl = port == 465

    use_tls_env = os.getenv("SMTP_USE_TLS") or os.getenv("MAIL_USE_TLS")
    if use_tls_env is not None:
        use_tls = use_tls_env.lower() in ("1", "true", "yes", "on")
    else:
        use_tls = port == 587 and not use_ssl

    sender = (
        os.getenv("SMTP_FROM")
        or os.getenv("MAIL_DEFAULT_SENDER")
        or (f"Facilita <{user}>" if user else "Facilita <noreply@facilita-br.vercel.app>")
    ).strip()

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "use_ssl": use_ssl,
        "use_tls": use_tls,
        "sender": sender,
    }


def is_email_configured() -> bool:
    """Verifica se há um servidor SMTP configurado."""
    cfg = obter_config_smtp()
    return bool(cfg["host"])


def formatar_tempo_espera(segundos: int) -> str:
    """Formata o tempo restante de bloqueio de forma amigável e legível."""
    if segundos <= 0:
        return "alguns instantes"
    if segundos < 60:
        return f"{segundos} segundo{'s' if segundos > 1 else ''}"
    minutos = (segundos + 59) // 60
    return f"{minutos} minuto{'s' if minutos > 1 else ''}"


def obter_whatsapp_suporte() -> str | None:
    """Retorna número normalizado do WhatsApp do administrador ou suporte."""
    val = (
        os.getenv("ADMIN_WHATSAPP")
        or os.getenv("WHATSAPP_SUPORTE")
        or os.getenv("CONTATO_SUPORTE")
        or ""
    ).strip()
    digits = re.sub(r"\D+", "", val)
    if not digits:
        return None
    if digits.startswith("55") and len(digits) in {12, 13}:
        return digits
    if len(digits) in {10, 11}:
        return f"55{digits}"
    return digits if 10 <= len(digits) <= 15 else None


def obter_link_whatsapp_ajuda(nome_cliente: str = "") -> str | None:
    """Gera link para contato direto no WhatsApp do administrador com mensagem pré-definida."""
    numero = obter_whatsapp_suporte()
    if not numero:
        return None
    from urllib.parse import quote
    msg = f"Olá, sou {nome_cliente.strip()}, perdi minha senha de acesso ao portal e preciso de ajuda para redefini-la." if nome_cliente.strip() else "Olá, perdi minha senha de acesso ao portal do cliente e preciso de ajuda para redefini-la."
    return f"https://wa.me/{numero}?text={quote(msg)}"


def enviar_email(
    destinatario: str,
    assunto: str,
    corpo_html: str,
    corpo_texto: str,
) -> tuple[bool, str]:
    """
    Envia um e-mail transacional usando smtplib.

    Retorna (sucesso: bool, mensagem_ou_erro: str).
    """
    cfg = obter_config_smtp()
    if not cfg["host"]:
        logger.info(
            "Servidor de e-mail não configurado. Disparo simulado para %s com assunto '%s'.",
            destinatario,
            assunto,
        )
        return False, "Servidor de e-mail não configurado nas variáveis de ambiente."

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = cfg["sender"]
    msg["To"] = destinatario
    msg.set_content(corpo_texto)
    msg.add_alternative(corpo_html, subtype="html")

    try:
        if cfg["use_ssl"]:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=10)
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=10)

        with server:
            if cfg["use_tls"]:
                server.starttls()
            if cfg["user"] and cfg["password"]:
                server.login(cfg["user"], cfg["password"])
            server.send_message(msg)

        logger.info("E-mail enviado com sucesso para %s.", destinatario)
        return True, "E-mail enviado com sucesso."
    except Exception as exc:
        logger.exception("Falha ao enviar e-mail para %s: %s", destinatario, exc)
        return False, str(exc)


def enviar_email_recuperacao(
    destinatario: str,
    nome: str,
    link_recuperacao: str,
    validade_minutos: int = 60,
) -> tuple[bool, str]:
    """
    Envia e-mail de recuperação de acesso com layout discreto e seguro.
    """
    primeiro_nome = nome.strip().split()[0] if nome.strip() else "Cliente"
    assunto = "Recuperação de acesso ao portal - Facilita"

    corpo_texto = f"""Olá, {primeiro_nome}.

Recebemos uma solicitação para redefinir a senha da sua conta de acompanhamento no Facilita.

Para criar uma nova senha, acesse o link abaixo:
{link_recuperacao}

Este link é pessoal, seguro e expira em {validade_minutos} minutos.

Se você não solicitou a redefinição de senha, desconsidere esta mensagem. Sua conta permanece segura.

Facilita · Gestão e Controle Financeiro
"""

    corpo_html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Recuperação de Acesso</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f4f6f8; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #172b4d;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #f4f6f8; padding: 40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 540px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(9, 30, 66, 0.08); border: 1px solid #dfe1e6;">
          <!-- Cabeçalho -->
          <tr>
            <td style="padding: 28px 32px; background: linear-gradient(135deg, #0052cc, #0747a6); text-align: left;">
              <span style="font-size: 22px; font-weight: 800; color: #ffffff; letter-spacing: -0.5px;">Facilita</span>
              <p style="margin: 4px 0 0 0; font-size: 13px; color: #deebff; letter-spacing: 0.5px; text-transform: uppercase;">Portal do Cliente</p>
            </td>
          </tr>
          <!-- Conteúdo Principal -->
          <tr>
            <td style="padding: 32px 32px 24px 32px;">
              <h1 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #172b4d;">Olá, {primeiro_nome}!</h1>
              <p style="margin: 0 0 18px 0; font-size: 15px; line-height: 1.6; color: #344563;">
                Recebemos uma solicitação para redefinir a sua senha de acesso ao portal de acompanhamento de operações e contratos.
              </p>
              <p style="margin: 0 0 24px 0; font-size: 15px; line-height: 1.6; color: #344563;">
                Clique no botão abaixo para escolher uma nova senha:
              </p>
              <!-- Botão de Ação -->
              <table role="presentation" cellspacing="0" cellpadding="0" style="margin: 0 0 28px 0;">
                <tr>
                  <td align="center" style="border-radius: 8px; background-color: #0052cc;">
                    <a href="{link_recuperacao}" target="_blank" style="display: inline-block; padding: 14px 28px; font-size: 15px; font-weight: 600; color: #ffffff; text-decoration: none; border-radius: 8px; border: 1px solid #0052cc;">
                      Redefinir minha senha
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin: 0 0 16px 0; font-size: 13px; line-height: 1.5; color: #5e6c84;">
                Ou copie e cole o link a seguir no seu navegador:<br>
                <a href="{link_recuperacao}" style="color: #0052cc; word-break: break-all; font-size: 12.5px;">{link_recuperacao}</a>
              </p>
              <div style="background-color: #fff8e1; border-left: 4px solid #ffab00; padding: 12px 14px; border-radius: 4px; margin: 24px 0 0 0;">
                <p style="margin: 0; font-size: 12.5px; line-height: 1.5; color: #7a5000;">
                  <strong>Aviso de segurança:</strong> Este link é exclusivo e expira em <strong>{validade_minutos} minutos</strong>. Se você não solicitou a redefinição, nenhuma alteração foi realizada e você pode desconsiderar esta mensagem com total segurança.
                </p>
              </div>
            </td>
          </tr>
          <!-- Rodapé -->
          <tr>
            <td style="padding: 20px 32px; background-color: #f7f8fa; border-top: 1px solid #ebecf0; text-align: center; font-size: 12px; color: #7a869a;">
              Facilita · Sistema Seguro de Controle Financeiro e Operações
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    return enviar_email(destinatario, assunto, corpo_html, corpo_texto)
