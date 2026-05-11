from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.application_material import ApplicationMaterial
from bccy_bot.db.models.enums import CT_PHOTO, CT_TEXT


async def add_photo(
    session: AsyncSession,
    application_id: int,
    material_type: str,
    telegram_file_id: str,
    original_message_id: int,
) -> ApplicationMaterial:
    m = ApplicationMaterial(
        application_id=application_id,
        material_type=material_type,
        content_type=CT_PHOTO,
        telegram_file_id=telegram_file_id,
        text_content=None,
        original_message_id=original_message_id,
    )
    session.add(m)
    await session.flush()
    return m


async def add_text(
    session: AsyncSession,
    application_id: int,
    material_type: str,
    text_content: str,
    original_message_id: int,
) -> ApplicationMaterial:
    m = ApplicationMaterial(
        application_id=application_id,
        material_type=material_type,
        content_type=CT_TEXT,
        telegram_file_id=None,
        text_content=text_content,
        original_message_id=original_message_id,
    )
    session.add(m)
    await session.flush()
    return m
