from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

def main_menu_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔍 Найти пункт")
    builder.button(text="📋 Отчёт")
    builder.button(text="📊 Статистика")
    builder.button(text="ℹ️ Помощь")
    builder.adjust(1, 1, 2)
    return builder.as_markup(resize_keyboard=True)

def report_type_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="🌅 Открытие пункта", callback_data="report_type:opening")
    builder.button(text="🚚 Приехала машина", callback_data="report_type:machine")
    builder.button(text="🔒 Закрытие пункта", callback_data="report_type:closing")
    builder.button(text="◀️ Назад", callback_data="step_back:point")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def fill_method_kb(report_type: str | None = None):
    builder = InlineKeyboardBuilder()
    if report_type == "closing":
        builder.button(text="⚡ Подставить из Турбо", callback_data="fill_method:turbo")
    builder.button(text="📝 По шагам", callback_data="fill_method:steps")
    builder.button(text="📄 Одним сообщением", callback_data="fill_method:one")
    builder.button(text="◀️ Назад", callback_data="step_back:types")
    builder.adjust(1)
    return builder.as_markup()

def confirm_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить в чат", callback_data="confirm_send")
    builder.button(text="✏️ Изменить", callback_data="edit_report")
    builder.button(text="◀️ Назад", callback_data="step_back:confirm")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def turbo_preview_kb():
    """Превью черновика из Турбо до дописывания недовоз / отправки."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📭 Указать недовоз и дальше", callback_data="turbo:nedovoz")
    builder.button(text="✅ К подтверждению (недовоз = 0)", callback_data="turbo:preview_zero_nedovoz")
    builder.button(text="✏️ Править текст", callback_data="edit_report")
    builder.button(text="◀️ Назад", callback_data="step_back:method")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def stats_period_kb(point_number: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="3 дня", callback_data=f"stats:{point_number}:3")
    builder.button(text="7 дней", callback_data=f"stats:{point_number}:7")
    builder.button(text="30 дней", callback_data=f"stats:{point_number}:30")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(3)
    return builder.as_markup()

def cancel_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel")
    return builder.as_markup()

def step_kb(back_to: str | None = None, now: str | None = None):
    builder = InlineKeyboardBuilder()
    if now:
        builder.button(text="🕐 Сейчас", callback_data=now)
    if back_to:
        builder.button(text="◀️ Назад", callback_data=f"step_back:{back_to}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def now_kb(callback_data: str, back_to: str | None = None):
    return step_kb(back_to=back_to, now=callback_data)

def machine_time_kb():
    return step_kb(back_to="method", now="machine_now")
