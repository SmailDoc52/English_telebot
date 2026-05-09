import os
import random
import time

import telebot
import sqlalchemy
from dotenv import load_dotenv
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker
from telebot import types, TeleBot, custom_filters
from telebot.storage import StateMemoryStorage
from telebot.handler_backends import State, StatesGroup

from models import create_tables, Users, Words, UserWords
from texts import welcome_msg, help_msg

# Загрузка конфигурации
load_dotenv()

db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")
db_name = os.getenv("DB_NAME")
tg_token = os.getenv("TG_TOKEN")

# Настройка FSM и инициализация бота
state_storage = StateMemoryStorage()
bot = TeleBot(tg_token, state_storage=state_storage)


class MyStates(StatesGroup):
    """Состояния для управления процессом обучения и добавления слов."""
    target_word = State()
    translate_word = State()
    add_word = State()


class DBManager:
    """Управление операциями удаления связей слов и пользователей."""
    @staticmethod
    def delete_word(word, chat_id):
        session = Session()
        try:
            # Поиск связи слова с пользователем через join
            db_line = (session.query(UserWords)
                       .join(Users)
                       .join(Words)
                       .filter(Words.translate_word == word,
                               Users.chat_id == chat_id)
                       .first())
            if db_line:
                session.delete(db_line)
                session.commit()
                return True
            return False
        except Exception as e:
            print(f"Ошибка удаления: {e}")
            return False
        finally:
            session.close()


@bot.message_handler(commands=['start'])
def start_bot(message):
    """Регистрация пользователя и выдача стартового набора слов."""
    bot.delete_state(message.from_user.id, message.chat.id)
    user_chat_id = message.chat.id
    bot.send_message(message.chat.id, f"Привет, {message.chat.first_name} 👋")
    time.sleep(0.5)

    session = Session()
    try:
        user = session.query(Users).filter_by(chat_id=user_chat_id).first()
        if not user:
            new_user = Users(chat_id=user_chat_id)
            session.add(new_user)
            session.commit()

            bot.send_message(message.chat.id, welcome_msg)

            all_words = session.query(Words).all()
            for word in all_words:
                user_word = UserWords(user_id=new_user.id, words_id=word.id)
                session.add(user_word)
            session.commit()
    except Exception as e:
        print(f"Ошибка регистрации: {e}")
        session.rollback()
    finally:
        session.close()
        send_question(message)


@bot.message_handler(commands=["add"])
@bot.message_handler(func=lambda message: message.text.
                     lower() == 'добавить слово')
def text_add(message):
    bot.set_state(message.from_user.id,
                  MyStates.add_word, message.chat.id)
    bot.send_message(message.chat.id, "Введи слово (Rus:Eng):")


@bot.message_handler(commands=['help'])
def helper(message):
    bot.delete_state(message.from_user.id, message.chat.id)
    bot.send_message(message.chat.id, help_msg)

@bot.message_handler(commands=['cards'])
def send_question(message):
    """Выбор случайного слова и формирование интерфейса карточки."""
    bot.delete_state(message.from_user.id, message.chat.id)
    user_chat_id = message.chat.id

    session = Session()
    try:
        # Получение списка слов пользователя
        words = (session.query(Words)
                 .join(UserWords)
                 .join(Users)
                 .filter(Users.chat_id == user_chat_id).all())

        if not words:
            bot.send_message(message.chat.id, ("У вас нет слов для изучения."
                                               "\nДобавить слово: /add"))
            return

        random_word_line = random.choice(words)
        target_word = random_word_line.target_word
        translate_word = random_word_line.translate_word

        # Выборка 3-х случайных вариантов для кнопок
        other_words = (session.query(Words)
                       .join(UserWords)
                       .join(Users)
                       .filter(Users.chat_id == user_chat_id,
                               Words.target_word != target_word)
                       .order_by(func.random())
                       .limit(3).all())

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True,
                                           row_width=2)
        buttons = [types.KeyboardButton(translate_word)]
        for word in other_words:
            buttons.append(types.KeyboardButton(word.translate_word))

        random.shuffle(buttons)
        markup.add(*buttons)
        markup.row(types.KeyboardButton("Пропустить"))
        markup.row(types.KeyboardButton("Добавить слово"),
                   types.KeyboardButton("Удалить слово"))

        bot.set_state(message.from_user.id,
                      MyStates.target_word, message.chat.id)
        with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
            data['target_word'] = target_word
            data['translate_word'] = translate_word

        bot.send_message(message.chat.id,
                         f"Как переводится {target_word}?",
                         reply_markup=markup)
    finally:
        session.close()


@bot.message_handler(func=lambda message: True, state=MyStates.target_word)
def check_answer(message):
    """Обработка ответа пользователя и навигационных кнопок."""
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        correct_answer = data['translate_word']
        target_word = data['target_word']

    msg_text = message.text.lower()

    if correct_answer.lower() == msg_text:
        bot.send_message(message.chat.id, "Правильно! ✅")
        bot.delete_state(message.from_user.id, message.chat.id)
        time.sleep(1)
        send_question(message)
    elif msg_text == 'пропустить':
        bot.delete_state(message.from_user.id, message.chat.id)
        send_question(message)
    elif msg_text == 'удалить слово':
        res = DBManager.delete_word(word=correct_answer,
                                    chat_id=message.chat.id)
        msg = f"Слово \"{target_word}\" удалено" if res else "Ошибка"
        bot.send_message(message.chat.id, msg)
        bot.delete_state(message.from_user.id, message.chat.id)
        send_question(message)
    elif msg_text == 'добавить слово':
        bot.delete_state(message.from_user.id, message.chat.id)
        bot.set_state(message.from_user.id,
                      MyStates.add_word, message.chat.id)
        bot.send_message(message.chat.id, "Введи слово (Rus:Eng):")
    else:
        bot.send_message(message.chat.id, "Не угадал ❌")


@bot.message_handler(func=lambda message: True, state=MyStates.add_word)
def add_word(message):
    """Парсинг ввода и добавление новой пары слов в базу данных."""
    session = Session()
    try:
        rus, eng = message.text.split(':')
        rus = rus.strip().capitalize()
        eng = eng.strip().capitalize()

        word_line = (session.query(Words)
                     .filter(Words.target_word == eng,
                             Words.translate_word == rus)
                     .first())

        user_line = (session.query(Users)
                     .filter(Users.chat_id == message.chat.id)
                     .first())

        if not word_line:
            word_line = Words(target_word=eng, translate_word=rus)
            session.add(word_line)
            session.commit()
            session.refresh(word_line)

        new_link = UserWords(user_id=user_line.id, words_id=word_line.id)
        session.add(new_link)
        session.commit()
        bot.send_message(message.chat.id, "Слово успешно добавлено!")
    except Exception as e:
        print(f"Error: {e}")
        bot.send_message(message.chat.id, "Ошибка формата.")
    finally:
        session.close()
        bot.delete_state(message.from_user.id, message.chat.id)
        send_question(message)


if __name__ == "__main__":
    DSN = (f'postgresql://{db_user}:{db_password}'
           f'@localhost:5432/{db_name}')
    engine = sqlalchemy.create_engine(DSN)

    create_tables(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    if session.query(Words).count() == 0:
        base_words = [
            Words(target_word='Peace', translate_word='Мир'),
            Words(target_word='Green', translate_word='Зеленый'),
            Words(target_word='White', translate_word='Белый'),
            Words(target_word='Hello', translate_word='Привет'),
            Words(target_word='Car', translate_word='Машина'),
            Words(target_word='Dog', translate_word='Собака'),
            Words(target_word='Cat', translate_word='Кот'),
            Words(target_word='Book', translate_word='Книга'),
            Words(target_word='Water', translate_word='Вода'),
            Words(target_word='Friend', translate_word='Друг'),
        ]
        session.add_all(base_words)
        session.commit()
    session.close()

    bot.add_custom_filter(custom_filters.StateFilter(bot))
    bot.polling(none_stop=True)