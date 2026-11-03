from aiogram.fsm.state import State, StatesGroup

class ReportStates(StatesGroup):
    waiting_point_number = State()
    choosing_report_type = State()
    choosing_fill_method = State()
    opening_date = State()
    opening_people_count = State()
    opening_names = State()
    machine_time = State()
    closing_transport_number = State()
    closing_transport_date = State()
    closing_time = State()
    closing_accepted_total = State()
    closing_tya = State()
    closing_ktya = State()
    closing_shortage = State()
    closing_excess = State()
    closing_zasyl = State()
    closing_issued = State()
    closing_leftover = State()
    waiting_one_message = State()
    choosing_edit_field = State()
    editing_field_value = State()
    confirming = State()

class StatsStates(StatesGroup):
    waiting_point_number = State()

class SearchStates(StatesGroup):
    waiting_query = State()

class AdminStates(StatesGroup):
    waiting_point_number = State()
    waiting_chat_id = State()
    waiting_place_pp = State()
    waiting_place_ozon = State()
    waiting_place_address = State()
