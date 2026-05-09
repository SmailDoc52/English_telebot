import sqlalchemy as sq
from sqlalchemy.orm import declarative_base
from sqlalchemy import UniqueConstraint

Base = declarative_base()


class Users(Base):
    """Модель пользователя бота."""
    __tablename__ = 'users'
    id = sq.Column(sq.Integer, primary_key=True)
    chat_id = sq.Column(sq.BigInteger, unique=True, nullable=False)


class Words(Base):
    """Модель словаря (общая для всех)."""
    __tablename__ = 'words'
    id = sq.Column(sq.Integer, primary_key=True)
    target_word = sq.Column(sq.String, nullable=False)
    translate_word = sq.Column(sq.String, nullable=False)
    is_common = sq.Column(sq.Boolean, default=False)

    # Защита от дублей пар слово-перевод
    __table_args__ = (
        UniqueConstraint('target_word',
                         'translate_word',
                         name='_word_pair_uc'),
    )


class UserWords(Base):
    """Таблица связей между пользователями и их словами."""
    __tablename__ = 'user_words'
    user_id = sq.Column(sq.Integer,
                        sq.ForeignKey('users.id'),
                        primary_key=True)
    words_id = sq.Column(sq.Integer,
                         sq.ForeignKey('words.id'),
                         primary_key=True)


def create_tables(engine):
    """Инициализация структуры БД."""
    # В продакшене drop_all обычно не используется
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)