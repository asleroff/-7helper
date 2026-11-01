from aiogram import Router, F, Bot
from aiogram.enums import ChatType
from aiogram.types import Message, CallbackQuery, LinkPreviewOptions
from aiogram.filters import Command, CommandStart
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from datetime import datetime
from html import escape
from urllib.parse import quote
import re

from states import ReportStates, StatsStates, SearchStates, AdminStates
from keyboards import *
import addresses
import database as db
import turbo_draft

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await db.add_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )
    await message.answer(
        "👋 Привет. Помогу найти пункт или отправить отчёт.\n\n"
        "«🔍 Найти пункт» — номер ПП, номер из ссылки или адрес.\n"
        "«📋 Отчёт» — текст уйдёт в чат пункта.",
        reply_markup=main_menu_kb()
    )

@router.message(F.text == "🔍 Найти пункт")
@router.message(Command("find"))
async def start_search(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(SearchStates.waiting_query)
    await message.answer(
        "🔍 Что знаешь о пункте? Хватит любого из этого:\n"
        "• номер ПП: 1125 или ПП_1125\n"
        "• номер пункта или ссылка ozon.ru/point/...\n"
        "• улица или часть адреса, например Заречный\n\n"
        "Следующим сообщением можно искать другой пункт.",
        reply_markup=main_menu_kb(),
    )

@router.message(F.text == "ℹ️ Помощь")
@router.message(Command("help"))
async def show_help(message: Message):
    await message.answer(
        "ℹ️ <b>Что я умею</b>\n\n"
        "🔍 <b>Найти пункт</b>\n"
        "Напиши номер ПП (<code>1125</code> или <code>ПП_1125</code>), "
        "номер из ссылки или саму ссылку <code>ozon.ru/point/...</code>, "
        "либо часть адреса, например улицу.\n"
        "В ответе будут номер ПП, номер пункта, адрес и кнопка «тут» на Яндекс Карты.\n\n"
        "📋 <b>Отчёт</b>\n"
        "Напиши номер ПП и выбери тип: открытие, машина или закрытие.\n"
        "Для закрытия можно подставить черновик из расширения Турбо ПВЗ, "
        "пройти по шагам или прислать текст одним сообщением. "
        "Перед отправкой покажу, как отчёт выглядит. "
        "«◀️ Назад» вернёт к предыдущему вопросу, «❌ Отмена» всё сбросит.\n\n"
        "📊 <b>Статистика</b>\n"
        "Напиши номер ПП и выбери 3, 7 или 30 дней. "
        "Покажу приёмку, выдачу и остаток по закрытиям этого пункта.\n\n"
        "❓ Если запутался или что-то не работает, напиши создателю: "
        "<a href=\"https://t.me/petyunyka\">@petyunyka</a>",
        reply_markup=main_menu_kb(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )

@router.message(F.text == "📊 Статистика")
@router.message(Command("stats"))
async def start_stats(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(StatsStates.waiting_point_number)
    await message.answer(
        "📊 По какому ПП показать статистику? Напиши номер, например 1125.",
        reply_markup=step_kb(),
    )

@router.message(StatsStates.waiting_point_number)
async def stats_point_number(message: Message, state: FSMContext):
    if message.text in {"📋 Отчёт", "🔍 Найти пункт", "ℹ️ Помощь", "📊 Статистика"}:
        raise SkipHandler()
    if not message.text or not message.text.strip():
        await message.answer("💬 Напиши номер ПП цифрами, например 1125.")
        return
    point_number = re.sub(r"\D", "", message.text)
    if not point_number:
        await message.answer("✏️ Напиши номер ПП цифрами, например 1125.")
        return
    await state.clear()
    await message.answer(await format_stats_text(point_number, 7), reply_markup=stats_period_kb(point_number))

@router.callback_query(F.data.regexp(r"^stats:\d+:(3|7|30)$"))
async def stats_period(callback: CallbackQuery):
    _, point_number, days = callback.data.split(":")
    await callback.message.edit_text(
        await format_stats_text(point_number, int(days)),
        reply_markup=stats_period_kb(point_number),
    )
    await callback.answer()

async def format_stats_text(point_number: str, days: int) -> str:
    stats = await db.get_stats(point_number, days)
    title = f"📊 <b>ПП_{escape(point_number)}</b> за {days} дн."
    if not stats["count"]:
        return f"{title}\nЗакрытий за этот срок ещё нет."
    if stats["leftover_last"] is None:
        leftover = "в отчётах не было цифры остатка"
    else:
        leftover = f"последний {stats['leftover_last']} ед."
        if stats["leftover_avg"] is not None:
            leftover += f", в среднем {stats['leftover_avg']}"
    return (
        f"{title}\n"
        f"Закрытий: {stats['count']}\n\n"
        f"📥 Приёмка: {stats['total_accepted']} ед. всего, в среднем {stats['avg_accepted']}\n"
        f"📤 Выдача: {stats['total_issued']} ед. всего, в среднем {stats['avg_issued']}\n"
        f"🏬 Остаток: {leftover}"
    )

@router.message(F.text == "📋 Отчёт")
@router.message(Command("report"))
async def start_report(message: Message, state: FSMContext):
    await state.clear()
    await ask_step("point", state, message=message)

@router.message(ReportStates.waiting_point_number)
async def process_point_number(message: Message, state: FSMContext):
    point_number = re.sub(r'\D', '', message.text.strip())
    if not point_number:
        await message.answer("✏️ Напиши номер ПП цифрами, например 1125.")
        return

    point = await db.get_point(point_number)
    if not point:
        await message.answer(f"⚠️ ПП_{point_number} для отчётов ещё не привязан к чату. Напиши администратору.")
        await state.clear()
        return

    await state.update_data(point_number=point_number, chat_id=point["chat_id"])
    await ask_step("types", state, message=message)

@router.callback_query(F.data.startswith("report_type:"))
async def process_report_type(callback: CallbackQuery, state: FSMContext):
    report_type = callback.data.split(":")[1]
    await state.update_data(report_type=report_type)
    await ask_step("method", state, callback=callback)

@router.callback_query(F.data.startswith("step_back:"))
@router.callback_query(F.data == "back_to_types")
async def on_step_back(callback: CallbackQuery, state: FSMContext):
    target = "types" if callback.data == "back_to_types" else callback.data.split(":", 1)[1]
    if target == "confirm":
        data = await state.get_data()
        if data.get("fill_method") == "turbo":
            target = "turbo"
        elif data.get("fill_method") == "steps" and data.get("report_type") == "opening":
            target = "opening_names"
        elif data.get("fill_method") == "steps" and data.get("report_type") == "machine":
            target = "machine_time"
        elif data.get("fill_method") == "steps":
            target = "leftover"
        else:
            target = "one"
    try:
        await ask_step(target, state, callback=callback)
    except Exception:
        await callback.answer("Не получилось вернуться. Нажми «📋 Отчёт» и начни заново.", show_alert=True)

@router.callback_query(ReportStates.choosing_fill_method, F.data == "fill_method:one")
async def start_one_message(callback: CallbackQuery, state: FSMContext):
    await state.update_data(fill_method="one")
    await ask_step("one", state, callback=callback)

@router.callback_query(ReportStates.choosing_fill_method, F.data == "fill_method:steps")
async def start_steps(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    report_type = data.get("report_type")
    if report_type == "opening":
        today = datetime.now().strftime("%d.%m.%Y")
        await state.update_data(fill_method="steps", opening_date=today)
        await ask_step("opening_people", state, callback=callback)
    elif report_type == "machine":
        await state.update_data(fill_method="steps")
        await ask_step("machine_time", state, callback=callback)
    elif report_type == "closing":
        await state.update_data(fill_method="steps")
        await ask_step("closing_number", state, callback=callback)
    else:
        await callback.answer("👆 Сначала выбери тип отчёта.", show_alert=True)

@router.callback_query(ReportStates.choosing_fill_method, F.data == "fill_method:turbo")
async def start_turbo(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("report_type") != "closing":
        await callback.answer("⚡ Турбо только для закрытия пункта.", show_alert=True)
        return
    point_number = data.get("point_number")
    if not point_number:
        await callback.answer("Сначала укажи номер ПП.", show_alert=True)
        return

    await callback.answer("Забираю черновик…")
    try:
        payload = await turbo_draft.fetch_draft(point_number)
    except turbo_draft.DraftNotFound:
        await callback.message.edit_text(
            f"📭 Для ПП_{escape(point_number)} черновика из Турбо нет.\n\n"
            "Собери закрытие в расширении и нажми «Отправить боту», потом попробуй снова.",
            reply_markup=fill_method_kb("closing"),
        )
        await state.set_state(ReportStates.choosing_fill_method)
        return
    except turbo_draft.DraftApiError as e:
        await callback.message.edit_text(
            f"⚠️ {escape(str(e))}\n\n"
            "Нужен запущенный API черновиков (порт 8787) и то же расширение.",
            reply_markup=fill_method_kb("closing"),
        )
        await state.set_state(ReportStates.choosing_fill_method)
        return

    fields = turbo_draft.closing_fields_from_draft(payload)
    draft_pp = re.sub(r"\D", "", str(fields.get("point_number") or ""))
    if draft_pp and draft_pp != str(point_number):
        await callback.message.edit_text(
            f"⚠️ Черновик собран для ПП_{escape(draft_pp)}, а в отчёте выбран ПП_{escape(point_number)}.\n"
            "Открой нужный пункт в Турбо, собери снова или выбери другой ПП.",
            reply_markup=fill_method_kb("closing"),
        )
        await state.set_state(ReportStates.choosing_fill_method)
        return

    if not fields.get("closing_transport_date"):
        fields["closing_transport_date"] = datetime.now().strftime("%d.%m.%Y")

    missing = turbo_draft.missing_closing_fields(fields)
    update = {
        "fill_method": "turbo",
        "turbo_collected_at": fields.get("turbo_collected_at"),
        "turbo_preview_text": fields.get("turbo_preview_text"),
    }
    for key, value in fields.items():
        if key.startswith("closing_") and value is not None:
            update[key] = value
    # Недовоз из Турбо обычно пустой — спросим отдельно
    update.pop("closing_nedovoz", None)
    await state.update_data(**update)

    if missing:
        miss = ", ".join(missing)
        await callback.message.edit_text(
            f"⚠️ Черновик ПП_{escape(point_number)} неполный. Не хватает: {escape(miss)}.\n\n"
            "Собери ещё раз в расширении или заполни отчёт по шагам.",
            reply_markup=fill_method_kb("closing"),
        )
        await state.set_state(ReportStates.choosing_fill_method)
        return

    await ask_step("turbo", state, callback=callback, edit=True)

async def take_text(message: Message) -> str | None:
    if not message.text or not message.text.strip():
        await message.answer("💬 Нужен текст, стикер я не разберу.")
        return None
    return message.text.strip()

async def take_number(message: Message) -> int | None:
    text = await take_text(message)
    if text is None:
        return None
    if not text.isdigit():
        await message.answer("🔢 Тут нужно число, например 0 или 12.")
        return None
    return int(text)

def step_view(target: str, data: dict) -> tuple:
    point = data.get("point_number", "")
    opening_date = data.get("opening_date") or datetime.now().strftime("%d.%m.%Y")
    closing_date = data.get("closing_transport_date") or datetime.now().strftime("%d.%m.%Y")
    if target == "preview":
        report_text = escape(str(data.get("report_text") or ""))
        return (
            ReportStates.confirming,
            f"👀 Вот так уйдёт в чат:\n\n{report_text}\n\nОтправляем?",
            confirm_kb(),
        )
    if target == "turbo":
        preview_data = dict(data)
        preview_data["closing_nedovoz"] = data.get("closing_nedovoz")
        if preview_data.get("closing_nedovoz") is None:
            preview_data["closing_nedovoz"] = "(укажи вручную)"
        collected = data.get("turbo_collected_at") or "—"
        body = escape(build_report(preview_data))
        return (
            ReportStates.turbo_review,
            (
                f"⚡ Черновик из Турбо для ПП_{escape(str(point))}\n"
                f"Собран: {escape(str(collected))}\n\n"
                f"{body}\n\n"
                "Недовоз в Турбо нет — укажи число или поставь 0."
            ),
            turbo_preview_kb(),
        )
    views = {
        "point": (ReportStates.waiting_point_number, "📋 Напиши номер ПП, например 1125", step_kb()),
        "types": (ReportStates.choosing_report_type, f"📍 Пункт: ПП_{point}\nВыбери тип отчёта:", report_type_kb()),
        "method": (
            ReportStates.choosing_fill_method,
            "✍️ Как удобнее заполнить?",
            fill_method_kb(data.get("report_type")),
        ),
        "one": (ReportStates.waiting_one_message, "📄 Пришли готовый текст отчёта одним сообщением:", step_kb("method")),
        "opening_people": (
            ReportStates.opening_people_count,
            f"📅 Дата открытия: {opening_date}\n👥 Сколько сотрудников на смене?",
            step_kb("method"),
        ),
        "opening_names": (ReportStates.opening_names, "👤 Напиши ФИО сотрудников:", step_kb("opening_people")),
        "machine_time": (
            ReportStates.machine_time,
            "🚚 Во сколько приехала машина? Например 14:30",
            step_kb("method", now="machine_now"),
        ),
        "closing_number": (ReportStates.closing_transport_number, "📦 Номер перевозки, например 6522092", step_kb("method")),
        "closing_time": (
            ReportStates.closing_time,
            f"🕗 Во сколько закрыли перевозку?\n📅 В отчёте будет дата {closing_date}.",
            step_kb("closing_number", now="closing_now"),
        ),
        "accepted": (ReportStates.closing_accepted_total, "📥 Принято всего. Напиши число:", step_kb("closing_time")),
        "tya": (ReportStates.closing_tya, "📦 ТЯ (тарный ящик). Напиши число:", step_kb("accepted")),
        "ktya": (ReportStates.closing_ktya, "🗃️ КТЯ (картонный тарный ящик). Напиши число:", step_kb("tya")),
        "shortage": (ReportStates.closing_shortage, "⚠️ Недостачи. Напиши число:", step_kb("ktya")),
        "excess": (ReportStates.closing_excess, "➕ Излишки. Напиши число:", step_kb("shortage")),
        "zasyl": (ReportStates.closing_zasyl, "↪️ Засылы. Напиши число:", step_kb("excess")),
        "nedovoz": (ReportStates.closing_nedovoz, "📭 Недовоз. Напиши число:", step_kb("zasyl")),
        "issued": (ReportStates.closing_issued, "📤 Выдано. Напиши число:", step_kb("nedovoz")),
        "leftover": (ReportStates.closing_leftover, "🏬 Остатки на складе. Напиши число:", step_kb("issued")),
        "place_pp": (AdminStates.waiting_place_pp, "🏷 Номер ПП, например 1125 или ПП_1125:", step_kb()),
        "place_ozon": (
            AdminStates.waiting_place_ozon,
            "🔗 Номер пункта или ссылка, например https://ozon.ru/point/1401680:",
            step_kb("place_pp"),
        ),
        "place_address": (
            AdminStates.waiting_place_address,
            "📍 Фактический адрес, например Квартал Заречный 1Г:",
            step_kb("place_ozon"),
        ),
        "admin_point": (AdminStates.waiting_point_number, "🏷 Напиши номер ПП:", step_kb()),
        "admin_chat": (
            AdminStates.waiting_chat_id,
            "💬 Теперь перешли любое сообщение из чата этого пункта или напиши chat_id.",
            step_kb("admin_point"),
        ),
    }
    return views[target]

async def ask_step(
    target: str,
    state: FSMContext,
    message: Message | None = None,
    callback: CallbackQuery | None = None,
    edit: bool = True,
):
    data = await state.get_data()
    new_state, text, markup = step_view(target, data)
    await state.set_state(new_state)
    if callback is not None:
        if edit:
            await callback.message.edit_text(text, reply_markup=markup)
        else:
            await callback.message.answer(text, reply_markup=markup)
        await callback.answer()
        return
    await message.answer(text, reply_markup=markup)

def build_report(data: dict) -> str:
    header = f"ПП_{data.get('point_number', '')}"
    report_type = data.get("report_type")
    if report_type == "opening":
        lines = [
            header,
            "Открытие пункта",
            f"Дата: {data['opening_date']}",
            f"Сотрудников на смене: {data['opening_people_count']}",
            f"ФИО: {data['opening_names']}",
        ]
    elif report_type == "machine":
        lines = [
            header,
            "Приехала машина",
            f"Время: {data['machine_time']}",
        ]
    else:
        shipment = str(data["closing_transport_number"]).lstrip("#").strip()
        lines = [
            f"ПП-{data.get('point_number', '')}",
            f"Закрыли перевозку #{shipment} от {data['closing_transport_date']}.",
            f"Закрыли перевозку в {data['closing_time']}",
            f"Принято всего: {data['closing_accepted_total']} ед.",
            f"ТЯ: {data['closing_tya']}",
            f"КТЯ: {data['closing_ktya']}",
            f"Недостачи: {data['closing_shortage']}",
            f"Излишки: {data['closing_excess']}",
            f"Засылы: {data['closing_zasyl']}",
            f"Недовоз: {data['closing_nedovoz']}",
            f"Выдано: {data['closing_issued']} ед.",
            f"Остатки на складе: {data['closing_leftover']} ед.",
            "ПП - закрыто.",
        ]
        return "\n\n".join(lines)
    return "\n".join(lines)

async def show_preview(
    message: Message,
    state: FSMContext,
    report_text: str,
    accepted: int | None,
    issued: int | None,
    leftover: int | None = None,
):
    await state.update_data(report_text=report_text, accepted=accepted, issued=issued, leftover=leftover)
    await state.set_state(ReportStates.confirming)
    await message.answer(
        f"👀 Вот так уйдёт в чат:\n\n{escape(report_text)}\n\nОтправляем?",
        reply_markup=confirm_kb(),
    )

@router.message(ReportStates.opening_people_count)
async def process_opening_people_count(message: Message, state: FSMContext):
    count = await take_number(message)
    if count is None:
        return
    await state.update_data(opening_people_count=count)
    await ask_step("opening_names", state, message=message)

@router.message(ReportStates.opening_names)
async def process_opening_names(message: Message, state: FSMContext):
    text = await take_text(message)
    if text is None:
        return
    await state.update_data(opening_names=text)
    data = await state.get_data()
    await show_preview(message, state, build_report(data), None, None)

@router.callback_query(ReportStates.machine_time, F.data == "machine_now")
async def machine_now(callback: CallbackQuery, state: FSMContext):
    now = datetime.now().strftime("%H:%M")
    await state.update_data(machine_time=now)
    data = await state.get_data()
    await callback.message.edit_text(f"🕐 Время приезда: {now}")
    await show_preview(callback.message, state, build_report(data), None, None)
    await callback.answer()

@router.message(ReportStates.machine_time)
async def process_machine_time(message: Message, state: FSMContext):
    text = await take_text(message)
    if text is None:
        return
    await state.update_data(machine_time=text)
    data = await state.get_data()
    await show_preview(message, state, build_report(data), None, None)

@router.message(ReportStates.closing_transport_number)
async def process_closing_transport_number(message: Message, state: FSMContext):
    text = await take_text(message)
    if text is None:
        return
    number = text.lstrip("#").strip()
    if not number:
        await message.answer("📦 Напиши номер перевозки, например 6522092.")
        return
    today = datetime.now().strftime("%d.%m.%Y")
    await state.update_data(closing_transport_number=number, closing_transport_date=today)
    await ask_step("closing_time", state, message=message)

@router.message(ReportStates.closing_accepted_total)
async def process_closing_accepted_total(message: Message, state: FSMContext):
    value = await take_number(message)
    if value is None:
        return
    await state.update_data(closing_accepted_total=value)
    await ask_step("tya", state, message=message)

@router.message(ReportStates.closing_tya)
async def process_closing_tya(message: Message, state: FSMContext):
    value = await take_number(message)
    if value is None:
        return
    await state.update_data(closing_tya=value)
    await ask_step("ktya", state, message=message)

@router.message(ReportStates.closing_ktya)
async def process_closing_ktya(message: Message, state: FSMContext):
    value = await take_number(message)
    if value is None:
        return
    await state.update_data(closing_ktya=value)
    await ask_step("shortage", state, message=message)

@router.message(ReportStates.closing_shortage)
async def process_closing_shortage(message: Message, state: FSMContext):
    value = await take_number(message)
    if value is None:
        return
    await state.update_data(closing_shortage=value)
    await ask_step("excess", state, message=message)

@router.message(ReportStates.closing_excess)
async def process_closing_excess(message: Message, state: FSMContext):
    value = await take_number(message)
    if value is None:
        return
    await state.update_data(closing_excess=value)
    await ask_step("zasyl", state, message=message)

@router.message(ReportStates.closing_zasyl)
async def process_closing_zasyl(message: Message, state: FSMContext):
    value = await take_number(message)
    if value is None:
        return
    await state.update_data(closing_zasyl=value)
    await ask_step("nedovoz", state, message=message)

@router.message(ReportStates.closing_nedovoz)
async def process_closing_nedovoz(message: Message, state: FSMContext):
    value = await take_number(message)
    if value is None:
        return
    await state.update_data(closing_nedovoz=value)
    data = await state.get_data()
    if data.get("fill_method") == "turbo":
        await show_preview(
            message,
            state,
            build_report(data),
            data.get("closing_accepted_total"),
            data.get("closing_issued"),
            data.get("closing_leftover"),
        )
        return
    await ask_step("issued", state, message=message)

@router.callback_query(ReportStates.turbo_review, F.data == "turbo:nedovoz")
async def turbo_ask_nedovoz(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ReportStates.closing_nedovoz)
    await callback.message.edit_text(
        "📭 Сколько недовоз? Напиши число (можно 0):",
        reply_markup=step_kb("turbo"),
    )
    await callback.answer()

@router.callback_query(ReportStates.turbo_review, F.data == "turbo:preview_zero_nedovoz")
async def turbo_zero_nedovoz(callback: CallbackQuery, state: FSMContext):
    await state.update_data(closing_nedovoz=0)
    data = await state.get_data()
    await callback.message.edit_text("📭 Недовоз: 0")
    await show_preview(
        callback.message,
        state,
        build_report(data),
        data.get("closing_accepted_total"),
        data.get("closing_issued"),
        data.get("closing_leftover"),
    )
    await callback.answer()

@router.callback_query(ReportStates.turbo_review, F.data == "edit_report")
async def edit_turbo_report(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ReportStates.waiting_one_message)
    await callback.message.edit_text(
        "✏️ Пришли текст заново, одним сообщением:",
        reply_markup=step_kb("turbo"),
    )
    await callback.answer()

@router.message(ReportStates.closing_issued)
async def process_closing_issued(message: Message, state: FSMContext):
    value = await take_number(message)
    if value is None:
        return
    await state.update_data(closing_issued=value)
    await ask_step("leftover", state, message=message)

@router.callback_query(ReportStates.closing_time, F.data == "closing_now")
async def closing_now(callback: CallbackQuery, state: FSMContext):
    now = datetime.now().strftime("%H:%M")
    await state.update_data(closing_time=now)
    await callback.message.edit_text(f"🕗 Закрыли перевозку в {now}")
    await ask_step("accepted", state, callback=callback, edit=False)

@router.message(ReportStates.closing_time)
async def process_closing_time(message: Message, state: FSMContext):
    text = await take_text(message)
    if text is None:
        return
    await state.update_data(closing_time=text)
    await ask_step("accepted", state, message=message)

@router.message(ReportStates.closing_leftover)
async def process_closing_leftover(message: Message, state: FSMContext):
    value = await take_number(message)
    if value is None:
        return
    await state.update_data(closing_leftover=value)
    data = await state.get_data()
    await show_preview(
        message,
        state,
        build_report(data),
        data.get("closing_accepted_total"),
        data.get("closing_issued"),
        data.get("closing_leftover"),
    )

@router.message(ReportStates.waiting_one_message)
async def process_one_message(message: Message, state: FSMContext):
    report_text = await take_text(message)
    if report_text is None:
        return
    data = await state.get_data()

    accepted = issued = leftover = None
    if data.get("report_type") == "closing":
        acc = re.search(r"Принято всего\s*:?\s*(\d+)", report_text, re.I)
        iss = re.search(r"Выдано\s*:?\s*(\d+)", report_text, re.I)
        left = re.search(r"Остатк\w*(?:\s+на складе)?\s*:?\s*(\d+)", report_text, re.I)
        if acc:
            accepted = int(acc.group(1))
        if iss:
            issued = int(iss.group(1))
        if left:
            leftover = int(left.group(1))

    await show_preview(message, state, report_text, accepted, issued, leftover)

@router.callback_query(ReportStates.confirming, F.data == "edit_report")
async def edit_report(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ReportStates.waiting_one_message)
    await callback.message.edit_text(
        "✏️ Пришли текст заново, одним сообщением:",
        reply_markup=step_kb("preview"),
    )
    await callback.answer()

@router.callback_query(ReportStates.confirming, F.data == "confirm_send")
async def confirm_send(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    report_text = data.get("report_text")
    chat_id = data.get("chat_id")
    point_number = data.get("point_number")
    report_type = data.get("report_type")
    if not report_text or chat_id is None or not point_number or not report_type:
        await callback.answer("⚠️ Этот отчёт уже не собрать. Нажми «📋 Отчёт» и начни заново.", show_alert=True)
        return
    try:
        await bot.send_message(chat_id=chat_id, text=escape(report_text))
        await db.save_report(
            point_number=point_number,
            report_type=report_type,
            user_id=callback.from_user.id,
            data=report_text,
            accepted=data.get("accepted"),
            issued=data.get("issued"),
            leftover=data.get("leftover"),
        )
        await callback.message.edit_text("✅ Готово, отчёт ушёл в чат пункта.")
        await state.clear()
    except Exception as e:
        await callback.message.edit_text(f"❌ Не получилось отправить: {escape(str(e))}")
    await callback.answer()

@router.callback_query(F.data.in_({
    "fill_method:steps",
    "fill_method:one",
    "fill_method:turbo",
    "turbo:nedovoz",
    "turbo:preview_zero_nedovoz",
    "edit_report",
    "confirm_send",
    "machine_now",
    "closing_now",
}))
async def stale_report_button(callback: CallbackQuery):
    await callback.answer("⏳ Эта кнопка уже не работает. Нажми «📋 Отчёт» и начни заново.", show_alert=True)

@router.callback_query(F.data == "cancel")
async def cancel_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("👌 Хорошо, ничего не отправил.")
    await callback.answer()

@router.message(Command("my_id"))
async def my_id(message: Message):
    await message.answer(f"🪪 Твой ID: {message.from_user.id}")

@router.message(Command("add_point"))
async def add_point_start(message: Message, state: FSMContext):
    if not await db.is_admin(message.from_user.id):
        await message.answer("🔒 Эта команда только для администратора.")
        return
    await ask_step("admin_point", state, message=message)

@router.message(AdminStates.waiting_point_number)
async def add_point_number(message: Message, state: FSMContext):
    await state.update_data(point_number=message.text.strip())
    await ask_step("admin_chat", state, message=message)

@router.message(AdminStates.waiting_chat_id)
async def add_point_chat(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_id = message.forward_from_chat.id if message.forward_from_chat else None
    if not chat_id and message.text and message.text.lstrip("-").isdigit():
        chat_id = int(message.text.strip())
    
    if not chat_id:
        await message.answer("🤷 Не вижу чат. Перешли сообщение из группы или напиши chat_id.")
        return

    await db.add_point(data["point_number"], chat_id)
    await state.clear()
    await message.answer(f"✅ Чат для ПП_{data['point_number']} сохранил.")

def format_place(place: dict, heading: bool = True, note: str = "") -> str:
    pp = escape(str(place["pp_number"]))
    address = escape(str(place["address"]))
    lines = [f"<b>ПП_{pp}</b>{note}"] if heading else []
    ozon = place.get("ozon_id")
    if ozon:
        ozon = escape(str(ozon))
        lines.append(f"🔢 Номер пункта: <code>{ozon}</code>")
        lines.append(f"🔗 Ссылка: https://ozon.ru/point/{ozon}")
    elif heading:
        lines.append("🔢 Номер пункта пока не указан")
    lines.append(f"📍 Адрес: {address}")
    maps_url = "https://yandex.ru/maps/?text=" + quote(str(place["address"]))
    lines.append(f'🗺 На яндекс картах: <a href="{escape(maps_url)}">тут</a>')
    return "\n".join(lines)

def format_search_results(places: list[dict]) -> str:
    if len(places) == 1:
        place = places[0]
        pp = escape(str(place["pp_number"]))
        if place.get("ozon_id"):
            intro = f"✅ Нашёл ПП_{pp}. Номер пункта и адрес ниже."
        else:
            intro = f"📍 Нашёл ПП_{pp}. Номера пункта в базе пока нет, адрес ниже."
        return f"{intro}\n\n{format_place(place, heading=False)}"
    reasons = {place["matched_by"] for place in places}
    blocks = []
    for index, place in enumerate(places, start=1):
        note = f" — совпало по {escape(place['matched_by'])}" if len(reasons) > 1 else ""
        blocks.append(f"{index}. {format_place(place, note=note)}")
    return "📍 Нашёл несколько пунктов. Смотри, какой нужен:\n\n" + "\n\n".join(blocks)

@router.message(SearchStates.waiting_query)
async def search_place(message: Message):
    if not message.text or not message.text.strip():
        await message.answer("💬 Нужен текст: номер, ссылка или адрес.")
        return
    places = await addresses.search_places(message.text)
    if not places:
        await message.answer(
            "🤷 Такого пункта пока нет. Проверь номер или напиши улицу."
        )
        return
    await message.answer(format_search_results(places))

@router.message(Command("add_place"))
async def add_place_start(message: Message, state: FSMContext):
    if not await db.is_admin(message.from_user.id):
        await message.answer("🔒 Эта команда только для администратора.")
        return
    await ask_step("place_pp", state, message=message)

@router.message(AdminStates.waiting_place_pp, F.text)
async def add_place_pp(message: Message, state: FSMContext):
    pp_number = addresses.extract_pp(message.text) or (
        message.text.strip() if message.text.strip().isdigit() else None
    )
    if not pp_number:
        await message.answer("✏️ Нужен номер ПП цифрами, например 1125.")
        return
    await state.update_data(pp_number=pp_number)
    await ask_step("place_ozon", state, message=message)

@router.message(AdminStates.waiting_place_ozon, F.text)
async def add_place_ozon(message: Message, state: FSMContext):
    ozon_id = addresses.extract_ozon_id(message.text)
    if not ozon_id and message.text.strip().isdigit():
        ozon_id = message.text.strip()
    if not ozon_id:
        await message.answer("✏️ Пришли номер пункта цифрами или ссылку ozon.ru/point/...")
        return
    await state.update_data(ozon_id=ozon_id)
    await ask_step("place_address", state, message=message)

@router.message(AdminStates.waiting_place_address, F.text)
async def add_place_address(message: Message, state: FSMContext):
    address = message.text.strip()
    if len(address) < 3:
        await message.answer("📏 Адрес слишком короткий. Напиши его полностью.")
        return
    data = await state.get_data()
    try:
        result = await addresses.save_place(data["pp_number"], data["ozon_id"], address)
    except ValueError as error:
        await state.clear()
        await message.answer(f"⚠️ Этот номер пункта уже стоит у ПП_{error}.")
        return
    await state.clear()
    verb = "♻️ Обновил пункт" if result == "updated" else "✅ Записал пункт"
    place = await addresses.get_by_pp(data["pp_number"])
    await message.answer(f"{verb}.\n\n{format_place(place)}", reply_markup=main_menu_kb())
