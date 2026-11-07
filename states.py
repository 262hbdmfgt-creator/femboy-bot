# -*- coding: utf-8 -*-
from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    waiting_card_photo = State()
    waiting_card_rarity = State()
    waiting_card_description = State()
    waiting_edit_description = State()
    waiting_admin_code = State()
    waiting_broadcast = State()
    waiting_promo_code = State()
    waiting_admin_text = State()
    waiting_clan_rename = State()


class UserStates(StatesGroup):
    waiting_promo_code = State()
    waiting_clan_name = State()
    waiting_clan_transfer = State()

