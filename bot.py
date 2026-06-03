import os
import shutil
import zipfile
import asyncio
import logging
from typing import List, Union, Dict
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from TGConvertor import SessionManager

try:
    import rarfile
    RAR_SUPPORTED = True
except ImportError:
    RAR_SUPPORTED = False

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- State Management ---
class ConversionWorkflow(StatesGroup):
    waiting_for_input = State()
    input_format = State()
    file_path = State()
    session_string = State()
    is_string = State()

# --- Archive Utilities ---
def create_zip(file_paths: Union[str, List[str]], output_path: str) -> str:
    if not output_path.endswith('.zip'):
        output_path += '.zip'
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        for path in file_paths:
            if os.path.isfile(path):
                zipf.write(path, os.path.basename(path))
            elif os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, os.path.dirname(path))
                        zipf.write(file_path, arcname)
    return output_path

def extract_archive(archive_path: str, extract_to: str) -> str:
    os.makedirs(extract_to, exist_ok=True)
    if archive_path.lower().endswith('.zip'):
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
    elif archive_path.lower().endswith('.rar'):
        if not RAR_SUPPORTED:
            raise RuntimeError("rarfile package or unrar system dependency missing.")
        with rarfile.RarFile(archive_path, 'r') as rar_ref:
            rar_ref.extractall(extract_to)
    else:
        raise ValueError("Unsupported archive format. Send .zip or .rar.")
    return extract_to

# --- Keyboards ---
def get_input_file_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Telethon File", callback_data="in_telethon"),
            InlineKeyboardButton(text="Pyrogram File", callback_data="in_pyrogram")
        ],
        [
            InlineKeyboardButton(text="TData (Archive)", callback_data="in_tdata")
        ]
    ])

def get_input_string_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Telethon String", callback_data="in_telestr"),
            InlineKeyboardButton(text="Pyrogram String", callback_data="in_pyrostr")
        ]
    ])

def get_output_format_kb(exclude_format: str) -> InlineKeyboardMarkup:
    formats = [
        ("telethon", "Telethon File"), 
        ("pyrogram", "Pyrogram File"), 
        ("tdata", "TData (.zip)"),
        ("telestr", "Telethon String"),
        ("pyrostr", "Pyrogram String")
    ]
    
    buttons = []
    for fmt_id, display_name in formats:
        if fmt_id != exclude_format:
            buttons.append(InlineKeyboardButton(text=display_name, callback_data=f"out_{fmt_id}"))
            
    # Arrange buttons 2 per row
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# --- Handlers ---
@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "**TGConvertor Bot** ⚡️\n\n"
        "Send me a `.session` file, a `.zip`/`.rar` containing a TData folder, or a **Session String** to begin.",
        parse_mode="Markdown"
    )
    await state.set_state(ConversionWorkflow.waiting_for_input)

@dp.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    session_string = message.text.strip()
    
    # Basic check to filter out regular chat messages (session strings are typically long)
    if len(session_string) < 50:
        await message.answer("That string looks too short to be a valid session string. Please send a valid string, file, or archive.")
        return
        
    await state.update_data(session_string=session_string, is_string=True)
    
    await message.answer(
        "String detected. **Select the INPUT format:**", 
        reply_markup=get_input_string_kb(),
        parse_mode="Markdown"
    )

@dp.message(F.document)
async def handle_document(message: Message, state: FSMContext):
    user_dir = f"./temp/{message.from_user.id}"
    os.makedirs(user_dir, exist_ok=True)
    
    file_path = os.path.join(user_dir, message.document.file_name)
    
    status_msg = await message.answer("📥 Downloading file...")
    await bot.download(message.document, destination=file_path)
    
    await state.update_data(file_path=file_path, is_string=False)
    
    await status_msg.edit_text(
        "File downloaded. **Select the INPUT format:**", 
        reply_markup=get_input_file_kb(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("in_"))
async def select_input_format(callback: CallbackQuery, state: FSMContext):
    input_fmt = callback.data.split("_")[1]
    await state.update_data(input_format=input_fmt)
    
    display_name = input_fmt.upper()
    if "str" in input_fmt:
        display_name = input_fmt.replace("str", " STRING").upper()
        
    await callback.message.edit_text(
        f"Input selected: **{display_name}**\n\n**Select the OUTPUT format:**",
        reply_markup=get_output_format_kb(input_fmt),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("out_"))
async def execute_conversion(callback: CallbackQuery, state: FSMContext):
    output_fmt = callback.data.split("_")[1]
    data = await state.get_data()
    
    user_id = callback.from_user.id
    await callback.message.edit_text("⏳ Processing conversion...")
    
    try:
        result = await process_session(data, output_fmt, user_id)
        
        if result["type"] == "file":
            await callback.message.answer_document(FSInputFile(result["data"]))
            await callback.message.edit_text("✅ **Conversion successful!**", parse_mode="Markdown")
        elif result["type"] == "string":
            await callback.message.edit_text(
                f"✅ **Conversion successful! Here is your string:**\n\n`{result['data']}`", 
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logging.error(f"Conversion error: {e}")
        await callback.message.edit_text(f"❌ **Error during conversion:**\n`{str(e)}`", parse_mode="Markdown")
        
    finally:
        # Cleanup temp files
        shutil.rmtree(f"./temp/{user_id}", ignore_errors=True)
        await state.clear()
        await state.set_state(ConversionWorkflow.waiting_for_input)

# --- Conversion Logic Core ---
async def process_session(data: dict, output_format: str, user_id: int) -> Dict[str, str]:
    """Handles the extraction, TGConvertor ingestion, and output generation workflow."""
    input_format = data.get("input_format")
    is_string = data.get("is_string")
    working_dir = f"./temp/{user_id}"
    os.makedirs(working_dir, exist_ok=True)
    
    session = None
    
    # 1. LOAD SESSION INTO MANAGER
    if is_string:
        session_string = data.get("session_string")
        if input_format == "telestr":
            session = await SessionManager.from_telethon_string(session_string)
        elif input_format == "pyrostr":
            session = await SessionManager.from_pyrogram_string(session_string)
    else:
        file_path = data.get("file_path")
        input_target = file_path
        
        if input_format == "tdata":
            extract_dir = os.path.join(working_dir, "tdata_extracted")
            extract_archive(file_path, extract_dir)
            input_target = extract_dir
            
        if input_format == "telethon":
            session = await SessionManager.from_telethon_file(input_target)
        elif input_format == "pyrogram":
            session = await SessionManager.from_pyrogram_file(input_target)
        elif input_format == "tdata":
            session = await SessionManager.from_tdata_folder(input_target)

    # 2. EXPORT SESSION
    if output_format == "telestr":
        string_out = await session.to_telethon_string()
        return {"type": "string", "data": string_out}
        
    elif output_format == "pyrostr":
        string_out = await session.to_pyrogram_string()
        return {"type": "string", "data": string_out}
        
    else:
        output_target = os.path.join(working_dir, "converted_session")
        if output_format == "telethon":
            output_target += ".session"
            await session.to_telethon_file(output_target)
        elif output_format == "pyrogram":
            output_target += ".session"
            await session.to_pyrogram_file(output_target)
        elif output_format == "tdata":
            output_folder = os.path.join(working_dir, "tdata_out")
            await session.to_tdata_folder(output_folder)
            output_target = create_zip(output_folder, output_folder + ".zip")
            
        return {"type": "file", "data": output_target}

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
