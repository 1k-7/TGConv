import os
import shutil
import zipfile
import asyncio
import logging
from typing import List, Union, Dict
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
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
    waiting_for_input = State()
    input_format = State()
    file_path = State()
    session_string = State()
    is_string = State()

class ArchiveStandaloneWorkflow(StatesGroup):
    waiting_for_unzip = State()
    waiting_for_zip_files = State()


# --- Archive & Path Utilities ---
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

def find_tdata_root(base_path: str) -> str:
    # 1. Destroy Mac OS junk immediately
    for root, dirs, _ in os.walk(base_path, topdown=False):
        for name in dirs:
            if name == "__MACOSX":
                shutil.rmtree(os.path.join(root, name), ignore_errors=True)
                
    # 2. Look for the directory containing 'key_data' (standard TData signature)
    for root, _, files in os.walk(base_path):
        if any(f.startswith("key_data") for f in files):
            return root
            
    return base_path


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
            
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ==========================================
# COMMAND HANDLERS
# ==========================================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "**TGConvertor Bot** ⚡️\n\n"
        "Send me a `.session` file, a `.zip`/`.rar` containing a TData folder, or a **Session String** to begin conversion.\n\n"
        "You can also use /zip or /unzip for general archive management.",
        parse_mode="Markdown"
    )
    await state.set_state(ConversionWorkflow.waiting_for_input)

@dp.message(Command("unzip"))
async def cmd_unzip(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Send me any `.zip` or `.rar` file, and I will extract the contents for you.")
    await state.set_state(ArchiveStandaloneWorkflow.waiting_for_unzip)

@dp.message(Command("zip"))
async def cmd_zip(message: Message, state: FSMContext):
    await state.clear()
    if message.reply_to_message and message.reply_to_message.document:
        user_id = message.from_user.id
        working_dir = os.path.abspath(f"./temp/zip_single_{user_id}_{message.message_id}")
        os.makedirs(working_dir, exist_ok=True)
        
        doc = message.reply_to_message.document
        file_path = os.path.join(working_dir, doc.file_name)
        
        status_msg = await message.answer("📥 Downloading replied file...")
        await bot.download(doc, destination=file_path)
        
        await status_msg.edit_text("🗜 Zipping file...")
        try:
            base_name = os.path.splitext(doc.file_name)[0]
            output_archive = os.path.join(working_dir, f"{base_name}.zip")
            create_zip(file_path, output_archive)
            
            await message.answer_document(FSInputFile(output_archive))
            await status_msg.edit_text("✅ Zipping complete!")
        except Exception as e:
            await status_msg.edit_text(f"❌ Error zipping: `{str(e)}`", parse_mode="Markdown")
        finally:
            shutil.rmtree(working_dir, ignore_errors=True)
            await state.set_state(ConversionWorkflow.waiting_for_input)
        return

    await state.update_data(files_to_zip=[])
    await message.answer(
        "Send me the files you want to zip one by one.\n"
        "When you are finished, send the command /done to get your archive."
    )
    await state.set_state(ArchiveStandaloneWorkflow.waiting_for_zip_files)


# ==========================================
# STANDALONE ARCHIVE FILE HANDLERS
# ==========================================

@dp.message(ArchiveStandaloneWorkflow.waiting_for_unzip, F.document)
async def process_standalone_unzip(message: Message, state: FSMContext):
    user_id = message.from_user.id
    working_dir = os.path.abspath(f"./temp/unzip_{user_id}_{message.message_id}")
    os.makedirs(working_dir, exist_ok=True)
    
    file_path = os.path.join(working_dir, message.document.file_name)
    await bot.download(message.document, destination=file_path)
    
    status_msg = await message.answer("📦 Extracting...")
    
    try:
        extract_dir = os.path.join(working_dir, "extracted")
        extract_archive(file_path, extract_dir)
        find_tdata_root(extract_dir)
        
        for root, _, files in os.walk(extract_dir):
            for file in files:
                extracted_file_path = os.path.join(root, file)
                await message.answer_document(FSInputFile(extracted_file_path))
                
        await status_msg.edit_text("✅ Extraction complete!")
    except Exception as e:
        await status_msg.edit_text(f"❌ Error extracting: `{str(e)}`", parse_mode="Markdown")
    finally:
        shutil.rmtree(working_dir, ignore_errors=True)
        await state.clear()
        await state.set_state(ConversionWorkflow.waiting_for_input)

@dp.message(ArchiveStandaloneWorkflow.waiting_for_zip_files, F.document)
async def collect_files_for_zip(message: Message, state: FSMContext):
    user_id = message.from_user.id
    working_dir = os.path.abspath(f"./temp/zip_{user_id}")
    os.makedirs(working_dir, exist_ok=True)
    
    file_path = os.path.join(working_dir, message.document.file_name)
    await bot.download(message.document, destination=file_path)
    
    data = await state.get_data()
    files_list = data.get("files_to_zip", [])
    files_list.append(file_path)
    
    await state.update_data(files_to_zip=files_list)
    await message.answer(f"Added `{message.document.file_name}`. Send more or type /done.", parse_mode="Markdown")

@dp.message(ArchiveStandaloneWorkflow.waiting_for_zip_files, Command("done"))
async def process_standalone_zip(message: Message, state: FSMContext):
    data = await state.get_data()
    files_list = data.get("files_to_zip", [])
    user_id = message.from_user.id
    working_dir = os.path.abspath(f"./temp/zip_{user_id}")
    
    if not files_list:
        await message.answer("You didn't send any files! Zipping cancelled.")
        await state.clear()
        await state.set_state(ConversionWorkflow.waiting_for_input)
        return
        
    status_msg = await message.answer("🗜 Zipping files...")
    
    try:
        output_archive = os.path.join(working_dir, "Archive.zip")
        create_zip(files_list, output_archive)
        
        await message.answer_document(FSInputFile(output_archive))
        await status_msg.edit_text("✅ Zipping complete!")
    except Exception as e:
        await status_msg.edit_text(f"❌ Error zipping: `{str(e)}`", parse_mode="Markdown")
    finally:
        shutil.rmtree(working_dir, ignore_errors=True)
        await state.clear()
        await state.set_state(ConversionWorkflow.waiting_for_input)


# ==========================================
# CONVERSION HANDLERS
# ==========================================

@dp.message(ConversionWorkflow.waiting_for_input, F.text & ~F.text.startswith('/'))
async def handle_text(message: Message, state: FSMContext):
    session_string = message.text.strip()
    
    if len(session_string) < 50:
        await message.answer("That string looks too short to be a valid session string. Please send a valid string, file, or archive.")
        return
        
    await state.update_data(session_string=session_string, is_string=True)
    
    await message.answer(
        "String detected. **Select the INPUT format:**", 
        reply_markup=get_input_string_kb(),
        parse_mode="Markdown"
    )

@dp.message(ConversionWorkflow.waiting_for_input, F.document)
async def handle_document(message: Message, state: FSMContext):
    user_dir = os.path.abspath(f"./temp/{message.from_user.id}_{message.message_id}")
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
            # If multiple strings were generated, they'll be separated by '---'
            await callback.message.edit_text(
                f"✅ **Conversion successful! Here is your string(s):**\n\n`{result['data']}`", 
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logging.error(f"Conversion error: {e}")
        error_msg = str(e).lower()
        
        if any(word in error_msg for word in ["decrypt", "password", "pad block", "auth"]):
            reply_text = "❌ **Decryption Failed:** The session might be corrupted, or it is locked with a local passcode."
        elif "sqlite" in error_msg or "database" in error_msg:
            reply_text = "❌ **Database Error:** The session file appears to be corrupted or in an unsupported format."
        elif "unsupported" in error_msg or "format" in error_msg:
            reply_text = "❌ **Format Error:** The archive or session format is unsupported."
        else:
            reply_text = f"❌ **Error during conversion:**\n`{str(e)}`"
            
        await callback.message.edit_text(reply_text, parse_mode="Markdown")
        
    finally:
        file_path = data.get("file_path")
        if file_path:
            shutil.rmtree(os.path.dirname(file_path), ignore_errors=True)
        else:
            shutil.rmtree(os.path.abspath(f"./temp/conv_str_{user_id}"), ignore_errors=True)
            
        await state.clear()
        await state.set_state(ConversionWorkflow.waiting_for_input)


# ==========================================
# CONVERSION LOGIC CORE (MULTI-ACCOUNT)
# ==========================================

async def process_session(data: dict, output_format: str, user_id: int) -> Dict[str, str]:
    input_format = data.get("input_format")
    is_string = data.get("is_string")
    
    if not is_string and data.get("file_path"):
        working_dir = os.path.dirname(os.path.abspath(data.get("file_path")))
    else:
        working_dir = os.path.abspath(f"./temp/conv_str_{user_id}")
        os.makedirs(working_dir, exist_ok=True)
        
    sessions = []
    
    # 1. LOAD SESSIONS INTO MANAGER(S)
    if is_string:
        session_string = data.get("session_string")
        if input_format == "telestr":
            sessions.append(SessionManager.from_telethon_string(session_string))
        elif input_format == "pyrostr":
            sessions.append(SessionManager.from_pyrogram_string(session_string))
    else:
        file_path = os.path.abspath(data.get("file_path"))
        input_target = file_path
        
        if input_format == "tdata":
            extract_dir = os.path.join(working_dir, "tdata_extracted")
            extract_archive(file_path, extract_dir)
            input_target = find_tdata_root(extract_dir)
            
            # Direct `opentele` integration to scrape all embedded accounts
            from opentele.td import TDesktop
            try:
                td = TDesktop(input_target)
                for account in td.accounts:
                    sessions.append(SessionManager(
                        auth_key=account.authKey.key,
                        user_id=account.UserId,
                        dc_id=account.MainDcId
                    ))
            except Exception as e:
                raise ValueError(f"Failed to load TData (maybe password protected or corrupted): {str(e)}")
                
            if not sessions:
                raise ValueError("No valid sessions found in TData folder.")
                
        elif input_format == "telethon":
            sessions.append(await SessionManager.from_telethon_file(input_target))
        elif input_format == "pyrogram":
            sessions.append(await SessionManager.from_pyrogram_file(input_target))


    # 2. EXPORT SESSIONS
    if output_format in ["telestr", "pyrostr"]:
        strings_out = []
        for s in sessions:
            if output_format == "telestr":
                strings_out.append(s.to_telethon_string())
            elif output_format == "pyrostr":
                strings_out.append(s.to_pyrogram_string())
                
        if len(strings_out) == 1:
            return {"type": "string", "data": strings_out[0]}
        else:
            return {"type": "string", "data": "\n\n---\n\n".join(strings_out)}
            
    else:
        # File Outputs
        if len(sessions) == 1:
            s = sessions[0]
            output_target = os.path.join(working_dir, "converted_session")
            
            if output_format == "telethon":
                output_target += ".session"
                await s.to_telethon_file(output_target)
            elif output_format == "pyrogram":
                output_target += ".session"
                await s.to_pyrogram_file(output_target)
            elif output_format == "tdata":
                output_folder = os.path.join(working_dir, "tdata_out")
                await s.to_tdata_folder(output_folder)
                output_target = create_zip(output_folder, output_folder + ".zip")
                
            if not os.path.exists(output_target):
                expected_ext = ".zip" if output_format == "tdata" else ".session"
                for file in os.listdir(working_dir):
                    if file.endswith(expected_ext) and "converted_session" in file:
                        output_target = os.path.join(working_dir, file)
                        break
        else:
            # Multi-account batch processing logic
            output_folder = os.path.join(working_dir, "converted_sessions")
            os.makedirs(output_folder, exist_ok=True)
            
            for i, s in enumerate(sessions):
                sid = getattr(s, 'user_id', f"account_{i+1}")
                if output_format == "tdata":
                    folder_path = os.path.join(output_folder, f"tdata_{sid}")
                    await s.to_tdata_folder(folder_path)
                else:
                    file_path = os.path.join(output_folder, f"{sid}.session")
                    if output_format == "telethon":
                        await s.to_telethon_file(file_path)
                    elif output_format == "pyrogram":
                        await s.to_pyrogram_file(file_path)
                        
            # Repackage the multiple outputs into a single zip structure
            output_target = create_zip(output_folder, output_folder + ".zip")

        if not os.path.exists(output_target):
            raise FileNotFoundError(f"TGConvertor failed to generate the output file(s).")
            
        return {"type": "file", "data": output_target}


if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
