import os
import shutil
import zipfile
import asyncio
import logging
from typing import List, Union
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from TGConvertor import SessionManager

# Try to import rarfile for .rar extraction support
try:
    import rarfile
    RAR_SUPPORTED = True
except ImportError:
    RAR_SUPPORTED = False

# Setup Logging & Environment
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- State Management ---
class ConversionWorkflow(StatesGroup):
    waiting_for_file = State()
    input_format = State()
    file_path = State()


# --- Archive Utilities ---

def create_zip(file_paths: Union[str, List[str]], output_path: str) -> str:
    """Compresses a file, directory, or list of files into a ZIP archive."""
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
    """Extracts a .zip or .rar archive."""
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

def get_input_format_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Telethon", callback_data="in_telethon"),
            InlineKeyboardButton(text="Pyrogram", callback_data="in_pyrogram")
        ],
        [
            InlineKeyboardButton(text="TData (Archive)", callback_data="in_tdata")
        ]
    ])

def get_output_format_kb(exclude_format: str) -> InlineKeyboardMarkup:
    formats = ["telethon", "pyrogram", "tdata"]
    if exclude_format in formats:
        formats.remove(exclude_format)
    
    buttons = []
    for fmt in formats:
        display = "TData (.zip)" if fmt == "tdata" else fmt.capitalize()
        buttons.append(InlineKeyboardButton(text=display, callback_data=f"out_{fmt}"))
        
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


# --- Handlers ---

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "**TGConvertor Bot** ⚡️\n\n"
        "Send me a `.session` file or a `.zip`/`.rar` containing a TData folder to begin.",
        parse_mode="Markdown"
    )
    await state.set_state(ConversionWorkflow.waiting_for_file)

@dp.message(F.document)
async def handle_document(message: Message, state: FSMContext):
    user_dir = f"./temp/{message.from_user.id}"
    os.makedirs(user_dir, exist_ok=True)
    
    file_path = os.path.join(user_dir, message.document.file_name)
    
    status_msg = await message.answer("📥 Downloading file...")
    await bot.download(message.document, destination=file_path)
    
    await state.update_data(file_path=file_path)
    
    await status_msg.edit_text(
        "File downloaded. **Select the INPUT format:**", 
        reply_markup=get_input_format_kb(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("in_"))
async def select_input_format(callback: CallbackQuery, state: FSMContext):
    input_fmt = callback.data.split("_")[1]
    await state.update_data(input_format=input_fmt)
    
    await callback.message.edit_text(
        f"Input selected: **{input_fmt.upper()}**\n\n**Select the OUTPUT format:**",
        reply_markup=get_output_format_kb(input_fmt),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("out_"))
async def execute_conversion(callback: CallbackQuery, state: FSMContext):
    output_fmt = callback.data.split("_")[1]
    data = await state.get_data()
    input_fmt = data.get("input_format")
    file_path = data.get("file_path")
    user_id = callback.from_user.id
    
    await callback.message.edit_text("⏳ Processing conversion...")
    
    try:
        output_path = await process_session(input_fmt, output_fmt, file_path, user_id)
        await callback.message.answer_document(FSInputFile(output_path))
        await callback.message.edit_text("✅ **Conversion successful!**", parse_mode="Markdown")
        
    except Exception as e:
        logging.error(f"Conversion error: {e}")
        await callback.message.edit_text(f"❌ **Error during conversion:**\n`{str(e)}`", parse_mode="Markdown")
        
    finally:
        # Cleanup
        shutil.rmtree(f"./temp/{user_id}", ignore_errors=True)
        await state.clear()
        await state.set_state(ConversionWorkflow.waiting_for_file)


# --- Conversion Logic Core ---

async def process_session(input_format: str, output_format: str, file_path: str, user_id: int) -> str:
    working_dir = f"./temp/{user_id}"
    input_target = file_path
    
    # Pre-process TData archive using our utility
    if input_format == "tdata":
        extract_dir = os.path.join(working_dir, "tdata_extracted")
        extract_archive(file_path, extract_dir)
        input_target = extract_dir
    
    # Load into TGConvertor
    session = None
    if input_format == "telethon":
        session = await SessionManager.from_telethon_file(input_target)
    elif input_format == "pyrogram":
        session = await SessionManager.from_pyrogram_file(input_target)
    elif input_format == "tdata":
        session = await SessionManager.from_tdata_folder(input_target)
    
    # Export to requested format
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
        # Repackage into a .zip using our utility
        output_target = create_zip(output_folder, output_folder + ".zip")
        
    return output_target


if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
