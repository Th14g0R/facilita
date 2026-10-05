import unittest
from datetime import date, datetime, timezone, timedelta
from timezone_utils import (
    APP_TIMEZONE,
    agora_brasil,
    hoje_brasil,
    to_brasil,
    format_time_br,
    format_date_br,
    format_datetime_br,
    iso_agora_brasil,
)


class TestTimezoneUtils(unittest.TestCase):
    def test_registro_usuario_print(self):
        """Testa o caso exato reportado pelo usuário na auditoria: 17:06:37 UTC -> 14:06:37 Brasil."""
        timestamp_banco = "2026-10-05 17:06:37.156113+00"
        self.assertEqual(format_time_br(timestamp_banco), "14:06:37")
        self.assertEqual(format_date_br(timestamp_banco), "05/10/2026")
        self.assertEqual(format_datetime_br(timestamp_banco), "05/10/2026 14:06:37")

    def test_virada_noturna_sem_salto_de_dia(self):
        """Garante que às 22:30 em Fortaleza (01:30 UTC do dia seguinte), a data permaneça correta."""
        timestamp_utc_noite = "2026-10-06 01:30:00+00"
        self.assertEqual(format_date_br(timestamp_utc_noite), "05/10/2026")
        self.assertEqual(format_time_br(timestamp_utc_noite), "22:30:00")

    def test_formato_iso_com_z(self):
        iso_z = "2026-10-05T17:06:37Z"
        self.assertEqual(format_time_br(iso_z), "14:06:37")
        self.assertEqual(format_date_br(iso_z), "05/10/2026")

    def test_legado_sqlite_sem_offset(self):
        """CURRENT_TIMESTAMP do SQLite sem offset é UTC."""
        legado_sqlite = "2026-09-20 04:04:01"
        self.assertEqual(format_time_br(legado_sqlite), "01:04:01")
        self.assertEqual(format_date_br(legado_sqlite), "20/09/2026")

    def test_data_pura_preservada(self):
        """Datas de vencimento ou competência puras (YYYY-MM-DD) não sofrem deslocamento de horas."""
        data_pura = "2026-10-05"
        self.assertEqual(format_date_br(data_pura), "05/10/2026")
        self.assertEqual(to_brasil(data_pura), date(2026, 10, 5))

    def test_objeto_date_puro(self):
        d = date(2026, 10, 5)
        self.assertEqual(format_date_br(d), "05/10/2026")

    def test_novo_registro_com_offset_brasil(self):
        """Timestamp gravado já com o fuso -03:00 deve manter o mesmo horário."""
        novo_registro = "2026-10-05 14:06:37-03:00"
        self.assertEqual(format_time_br(novo_registro), "14:06:37")
        self.assertEqual(format_date_br(novo_registro), "05/10/2026")

    def test_agora_e_hoje_brasil(self):
        agora = agora_brasil()
        hoje = hoje_brasil()
        self.assertEqual(agora.date(), hoje)
        self.assertIsNotNone(agora.tzinfo)

    def test_iso_agora_brasil(self):
        iso_str = iso_agora_brasil()
        self.assertIn("-03:00", iso_str)


if __name__ == "__main__":
    unittest.main()
