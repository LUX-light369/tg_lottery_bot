from aiogram.fsm.state import StatesGroup, State

class LotterySetup(StatesGroup):
    choosing_mode = State()       # Выбор: Время или Участники
    entering_limit = State()      # Ввод минут или количества людей
    entering_winners = State()    # Ввод количества победителей
    entering_link = State()       # Ввод ссылки на канал/задание (обязательная подписка)
    entering_chat_id = State()    # Ввод ID группы, куда отправить розыгрыш
