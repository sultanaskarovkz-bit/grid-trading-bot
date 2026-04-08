"""
Telegram-уведомления на русском языке.
Отправляет сигналы, статусы и отчёты.

Настройка:
  1. Откройте @BotFather в Telegram -> /newbot -> получите TOKEN
  2. Напишите @userinfobot -> получите CHAT_ID
  3. Задайте переменные:
     TELEGRAM_BOT_TOKEN=ваш_токен
     TELEGRAM_CHAT_ID=ваш_chat_id
"""

import logging
import os
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:

    def __init__(self, token: str = "", chat_id: str = ""):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self._enabled = bool(self.token and self.chat_id)

        if not self._enabled:
            logger.warning(
                "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
            )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self._enabled:
            logger.debug(f"Telegram disabled. Message: {text[:80]}")
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return True
            logger.error(f"Telegram API error {resp.status_code}: {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def signal_open(self, symbol: str, direction: str, price: float,
                    level: int, lot_size: float, atr_pips: float,
                    trend: str, reason: str = "") -> bool:

        if direction == "long":
            icon = "\U0001f7e2"
            dir_text = "LONG (Покупка)"
            arrow = "\U00002b06\U0000fe0f"
        else:
            icon = "\U0001f534"
            dir_text = "SHORT (Продажа)"
            arrow = "\U00002b07\U0000fe0f"

        msg = f"{icon} <b>СИГНАЛ: {dir_text} {arrow}</b>\n\n"
        msg += f"<b>Пара:</b>      {symbol}\n"
        msg += f"<b>Цена входа:</b> {price:.5f}\n"

        if level > 0:
            msg += f"<b>Уровень:</b>   {level} (усреднение)\n"

        if lot_size > 0:
            msg += f"<b>Лот:</b>       {lot_size:.3f}\n"

        msg += f"\n<b>ATR:</b>       {atr_pips:.0f} пипсов\n"
        msg += f"<b>Тренд:</b>     {'Восходящий' if trend in ('UP', 'LONG') else 'Нисходящий' if trend in ('DOWN', 'SHORT') else 'Нейтральный'}\n"

        if reason:
            # Translate signal types
            reason_ru = reason
            reason_ru = reason_ru.replace("EMA_CROSSOVER", "Пересечение EMA")
            reason_ru = reason_ru.replace("TREND_PULLBACK", "Откат к EMA")
            reason_ru = reason_ru.replace("BREAKOUT", "Пробой диапазона")
            reason_ru = reason_ru.replace("MOMENTUM", "Сильный импульс")
            reason_ru = reason_ru.replace("crossover", "пересечение")
            reason_ru = reason_ru.replace("New grid entry (trend signal)", "Новый вход по тренду")
            reason_ru = reason_ru.replace("Grid level", "Уровень сетки")
            reason_ru = reason_ru.replace("averaging in", "усреднение")
            reason_ru = reason_ru.replace("strength:", "сила:")
            reason_ru = reason_ru.replace("STRONG", "Сильный")
            reason_ru = reason_ru.replace("MEDIUM", "Средний")
            reason_ru = reason_ru.replace("Pullback to", "Откат к")
            reason_ru = reason_ru.replace("in LONG trend", "в восходящем тренде")
            reason_ru = reason_ru.replace("in SHORT trend", "в нисходящем тренде")
            reason_ru = reason_ru.replace("Breakout above", "Пробой вверх")
            reason_ru = reason_ru.replace("Breakout below", "Пробой вниз")
            reason_ru = reason_ru.replace("20-bar high", "20-барный максимум")
            reason_ru = reason_ru.replace("20-bar low", "20-барный минимум")
            reason_ru = reason_ru.replace("ATR move", "движение ATR")
            msg += f"<b>Причина:</b>   {reason_ru}\n"

        msg += f"\n\U0001f552 <i>{datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC</i>"
        return self.send_message(msg)

    def signal_close(self, symbol: str, reason: str, pnl: float,
                     num_levels: int, holding_hours: float) -> bool:

        if pnl >= 0:
            icon = "\U00002705"
            result_text = f"+${pnl:.2f} \U0001f4b0"
            result_label = "ПРИБЫЛЬ"
        else:
            icon = "\U0000274c"
            result_text = f"-${abs(pnl):.2f}"
            result_label = "УБЫТОК"

        # Translate reason
        reason_map = {
            "TAKE_PROFIT": "Тейк-профит",
            "TRAILING_TP": "Трейлинг-стоп",
            "PAIR_STOP": "Стоп-лосс по паре",
            "HARD_STOP": "Аварийный стоп портфеля",
            "END_OF_TEST": "Конец теста",
        }
        reason_ru = reason_map.get(reason, reason)

        # Format holding time
        if holding_hours < 1:
            time_text = f"{int(holding_hours * 60)} мин"
        elif holding_hours < 24:
            time_text = f"{holding_hours:.1f} ч"
        else:
            days = holding_hours / 24
            time_text = f"{days:.1f} дн"

        msg = f"{icon} <b>СДЕЛКА ЗАКРЫТА: {symbol}</b>\n\n"
        msg += f"<b>Результат:</b>   {result_label}\n"
        msg += f"<b>P&L:</b>         {result_text}\n"
        msg += f"<b>Причина:</b>     {reason_ru}\n"
        msg += f"<b>Уровней:</b>     {num_levels}\n"
        msg += f"<b>Длительность:</b> {time_text}\n"
        msg += f"\n\U0001f552 <i>{datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC</i>"
        return self.send_message(msg)

    def portfolio_update(self, equity: float, unrealized_pnl: float,
                         active_pairs: int, drawdown_pct: float,
                         daily_pnl: float) -> bool:

        dd_icon = "\U000026a0\U0000fe0f" if drawdown_pct > 10 else "\U00002705"
        daily_icon = "\U0001f4c8" if daily_pnl >= 0 else "\U0001f4c9"

        msg = f"\U0001f4ca <b>СТАТУС ПОРТФЕЛЯ</b>\n\n"
        msg += f"<b>Баланс:</b>         ${equity:,.2f}\n"
        msg += f"<b>Плавающий P&L:</b>  ${unrealized_pnl:+,.2f}\n"
        msg += f"{daily_icon} <b>За сегодня:</b>     ${daily_pnl:+,.2f}\n"
        msg += f"<b>Активных пар:</b>   {active_pairs}\n"
        msg += f"{dd_icon} <b>Просадка:</b>       {drawdown_pct:.1f}%\n"
        msg += f"\n\U0001f552 <i>{datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC</i>"
        return self.send_message(msg)

    def market_analysis(self, analyses: list[dict]) -> bool:

        msg = "\U0001f50d <b>ОБЗОР РЫНКА</b>\n\n"

        for a in analyses:
            if a["trend"] == "UP":
                trend_icon = "\U00002b06\U0000fe0f"
                trend_text = "Рост"
            elif a["trend"] == "DOWN":
                trend_icon = "\U00002b07\U0000fe0f"
                trend_text = "Падение"
            else:
                trend_icon = "\U000027a1\U0000fe0f"
                trend_text = "Флэт"

            signal = a.get("signal", "WAIT")
            signal_map = {
                "LONG": "Покупка",
                "SHORT": "Продажа",
                "WAIT": "Ожидание",
            }
            signal_ru = signal_map.get(signal, signal)
            if "IN TRADE" in signal:
                signal_ru = signal.replace("IN TRADE", "В сделке")

            strength = a.get("strength", "")
            strength_map = {
                "READY": "Готов",
                "no trend": "нет тренда",
            }
            strength_ru = strength_map.get(strength, strength)
            if "BLOCKED" in strength:
                strength_ru = strength.replace("BLOCKED", "Заблокирован")

            msg += (
                f"{trend_icon} <b>{a['symbol']}</b>: "
                f"{trend_text} | ATR {a['atr_pips']:.0f}п | "
                f"{signal_ru}"
            )
            if strength_ru:
                msg += f" ({strength_ru})"
            msg += "\n"

        msg += f"\n\U0001f552 <i>{datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC</i>"
        return self.send_message(msg)

    def error_alert(self, error_msg: str) -> bool:
        msg = (
            f"\U0001f6a8 <b>ОШИБКА</b>\n\n"
            f"{error_msg}\n\n"
            f"\U0001f552 <i>{datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC</i>"
        )
        return self.send_message(msg)

    def bot_started(self, pairs: list[str], mode: str) -> bool:
        mode_map = {"SIGNALS": "Сигналы", "LIVE": "Торговля"}
        msg = (
            f"\U0001f680 <b>БОТ ЗАПУЩЕН</b>\n\n"
            f"<b>Режим:</b> {mode_map.get(mode, mode)}\n"
            f"<b>Пары:</b> {', '.join(pairs)}\n\n"
            f"\U0001f552 <i>{datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC</i>"
        )
        return self.send_message(msg)

    def bot_stopped(self, reason: str = "manual") -> bool:
        reason_map = {"manual": "Ручная остановка", "shutdown": "Завершение работы"}
        msg = (
            f"\U000026d4 <b>БОТ ОСТАНОВЛЕН</b>\n\n"
            f"<b>Причина:</b> {reason_map.get(reason, reason)}\n\n"
            f"\U0001f552 <i>{datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC</i>"
        )
        return self.send_message(msg)
