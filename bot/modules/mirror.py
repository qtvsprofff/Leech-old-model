import requests
import logging

from re import match, search, split as resplit
from time import sleep, time
import os
from os import path as ospath, remove as osremove, listdir, walk
from shutil import rmtree
from threading import Thread
from subprocess import run as srun
from pathlib import PurePath
from urllib.parse import quote
from telegram.ext import CommandHandler, MessageHandler, Filters
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Bot, Message

from bot import Interval, INDEX_URL, BUTTON_FOUR_NAME, BUTTON_FOUR_URL, BUTTON_FIVE_NAME, BUTTON_FIVE_URL, \
                BUTTON_SIX_NAME, BUTTON_SIX_URL, BLOCK_MEGA_FOLDER, BLOCK_MEGA_LINKS, VIEW_LINK, aria2, QB_SEED, \
                dispatcher, DOWNLOAD_DIR, download_dict, download_dict_lock, TG_SPLIT_SIZE, LOGGER, BOT_PM
from bot.helper.ext_utils.bot_utils import get_readable_file_size, is_url, is_magnet, is_gdtot_link, is_mega_link, is_gdrive_link, get_content_type, get_mega_link_type
from bot.helper.ext_utils.fs_utils import get_base_name, get_path_size, split as fssplit, clean_download
from bot.helper.ext_utils.shortenurl import short_url
from bot.helper.ext_utils.exceptions import DirectDownloadLinkException, NotSupportedExtractionArchive
from bot.helper.mirror_utils.download_utils.aria2_download import add_aria2c_download
from bot.helper.mirror_utils.download_utils.mega_downloader import add_mega_download
from bot.helper.mirror_utils.download_utils.gd_downloader import add_gd_download
from bot.helper.mirror_utils.download_utils.qbit_downloader import add_qb_torrent
from bot.helper.mirror_utils.download_utils.direct_link_generator import direct_link_generator
from bot.helper.mirror_utils.download_utils.telegram_downloader import TelegramDownloadHelper
from bot.helper.mirror_utils.status_utils.extract_status import ExtractStatus
from bot.helper.mirror_utils.status_utils.zip_status import ZipStatus
from bot.helper.mirror_utils.status_utils.split_status import SplitStatus
from bot.helper.mirror_utils.status_utils.upload_status import UploadStatus
from bot.helper.mirror_utils.status_utils.tg_upload_status import TgUploadStatus
from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.mirror_utils.upload_utils.pyrogramEngine import TgUploader
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import sendMessage, sendMarkup, delete_all_messages, update_all_messages, sendLog, sendPrivate, sendtextlog, editMessage, auto_delete
from bot.helper.telegram_helper.button_build import ButtonMaker

logger = logging.getLogger(__name__)

class MirrorListener:
    def __init__(self, bot, update: Update, isZip=False, extract=False, isQbit=False, isLeech=False, pswd=None, tag=None):
        self.bot = bot
        self.update = update
        self.message: Message = update.message if update.message is not None else update.channel_post
        self.message.from_user = update.message.from_user if update.message is not None else update.channel_post.chat
        self.uid = self.message.message_id
        self.extract = extract
        self.isZip = isZip
        self.isQbit = isQbit
        self.isLeech = isLeech
        self.pswd = pswd
        self.tag = tag

    def clean(self):
        try:
            aria2.purge()
            Interval[0].cancel()
            del Interval[0]
            delete_all_messages()
        except IndexError:
            pass

    def onDownloadComplete(self):
        with download_dict_lock:
            LOGGER(__name__).info(f"Download completed: {download_dict[self.uid].name()}")
            download = download_dict[self.uid]
            name = str(download.name()).replace('/', '')
            gid = download.gid()
            size = download.size_raw()
            if name == "None" or self.isQbit:
                name = listdir(f'{DOWNLOAD_DIR}{self.uid}')[-1]
            m_path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
        if self.isZip:
            try:
                with download_dict_lock:
                    download_dict[self.uid] = ZipStatus(name, m_path, size)
                pswd = self.pswd
                path = m_path + ".zip"
                LOGGER(__name__).info(f'Zip: orig_path: {m_path}, zip_path: {path}')
                if pswd is not None:
                    if self.isLeech and int(size) > TG_SPLIT_SIZE:
                        path = m_path + ".zip"
                        srun(["7z", f"-v{TG_SPLIT_SIZE}b", "a", "-mx=0", f"-p{pswd}", path, m_path])
                    else:
                        srun(["7z", "a", "-mx=0", f"-p{pswd}", path, m_path])
                elif self.isLeech and int(size) > TG_SPLIT_SIZE:
                    path = m_path + ".zip"
                    srun(["7z", f"-v{TG_SPLIT_SIZE}b", "a", "-mx=0", path, m_path])
                else:
                    srun(["7z", "a", "-mx=0", path, m_path])
            except FileNotFoundError:
                LOGGER(__name__).info('File to archive not found!')
                self.onUploadError('Internal error occurred!!')
                return
            try:
                rmtree(m_path, ignore_errors=True)
            except:
                osremove(m_path)
        elif self.extract:
            try:
                if ospath.isfile(m_path):
                    path = get_base_name(m_path)
                LOGGER(__name__).info(f"Extracting: {name}")
                with download_dict_lock:
                    download_dict[self.uid] = ExtractStatus(name, m_path, size)
                pswd = self.pswd
                if ospath.isdir(m_path):
                    for dirpath, subdir, files in walk(m_path, topdown=False):
                        for file_ in files:
                            if search(r'\.part0*1.rar$', file_) or search(r'\.7z.0*1$', file_) \
                               or (file_.endswith(".rar") and not search(r'\.part\d+.rar$', file_)) \
                               or file_.endswith(".zip") or search(r'\.zip.0*1$', file_):
                                m_path = ospath.join(dirpath, file_)
                                if pswd is not None:
                                    result = srun(["7z", "x", f"-p{pswd}", m_path, f"-o{dirpath}", "-aot"])
                                else:
                                    result = srun(["7z", "x", m_path, f"-o{dirpath}", "-aot"])
                                if result.returncode != 0:
                                    LOGGER(__name__).error('Unable to extract archive!')
                        for file_ in files:
                            if file_.endswith(".rar") or search(r'\.r\d+$', file_) \
                               or search(r'\.7z.\d+$', file_) or search(r'\.z\d+$', file_) \
                               or search(r'\.zip.\d+$', file_) or file_.endswith(".zip"):
                                del_path = ospath.join(dirpath, file_)
                                osremove(del_path)
                    path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
                else:
                    if pswd is not None:
                        result = srun(["bash", "pextract", m_path, pswd])
                    else:
                        result = srun(["bash", "extract", m_path])
                    if result.returncode == 0:
                        LOGGER(__name__).info(f"Extract Path: {path}")
                        osremove(m_path)
                        LOGGER(__name__).info(f"Deleting archive: {m_path}")
                    else:
                        LOGGER(__name__).error('Unable to extract archive! Uploading anyway')
                        path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
            except NotSupportedExtractionArchive:
                LOGGER(__name__).info("Not any valid archive, uploading file as it is.")
                path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
        else:
            path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
        if "www.1TamilMV.cloud" in path or "www.TamilBlasters.cfd" in path:
            new_path = path.replace("www.1TamilMV.cloud", "@KaipullaVadiveluOffl").replace("www.TamilBlasters.cfd", "@KaipullaVadiveluOffl")
            os.rename(path, new_path)
            path = new_path
        up_name = PurePath(path).name
        up_path = f'{DOWNLOAD_DIR}{self.uid}/{up_name}'
        size = get_path_size(f'{DOWNLOAD_DIR}{self.uid}')
        if self.isLeech and not self.isZip:
            checked = False
            for dirpath, subdir, files in walk(f'{DOWNLOAD_DIR}{self.uid}', topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    f_size = ospath.getsize(f_path)
                    if int(f_size) > TG_SPLIT_SIZE:
                        if not checked:
                            checked = True
                            with download_dict_lock:
                                download_dict[self.uid] = SplitStatus(up_name, up_path, size)
                            LOGGER(__name__).info(f"Splitting: {up_name}")
                        fssplit(f_path, f_size, file_, dirpath, TG_SPLIT_SIZE)
                        osremove(f_path)
        if self.isLeech:
            LOGGER(__name__).info(f"Leech Name: {up_name}")
            tg = TgUploader(up_name, self)
            tg_upload_status = TgUploadStatus(tg, size, gid, self)
            with download_dict_lock:
                download_dict[self.uid] = tg_upload_status
            update_all_messages()
            tg.upload()
        else:
            LOGGER(__name__).info(f"Upload Name: {up_name}")
            drive = GoogleDriveHelper(up_name, self)
            upload_status = UploadStatus(drive, size, gid, self)
            with download_dict_lock:
                download_dict[self.uid] = upload_status
            update_all_messages()
            drive.upload(up_name)

    def onDownloadError(self, error):
        error = error.replace('<', ' ') 
        error = error.replace('>', ' ')
        with download_dict_lock:
            try:
                download = download_dict[self.uid]
                del download_dict[self.uid]
                clean_download(download.path())
            except Exception as e:
                LOGGER(__name__).exception(str(e), exc_info=True)
            count = len(download_dict)
        msg = f"{self.tag}, Your download has been stopped.\n\n<b>Reason:</b> {error} #KristyCloud"
        chat_id = self.message.chat.id
        sendMessage(msg, self.bot, self.update, chat_id=chat_id)
        if count == 0:
            self.clean()
        else:
            update_all_messages()

    def onUploadComplete(self, link: str, size, files, folders, typ):
        if self.isLeech:
            if self.isQbit and QB_SEED:
                pass
            else:
                with download_dict_lock:
                    try: 
                        clean_download(download_dict[self.uid].path())
                    except FileNotFoundError:
                        pass
                    del download_dict[self.uid]
                    dcount = len(download_dict)
                if dcount == 0:
                    self.clean()
                else:
                    update_all_messages()
            count = len(files)
            msg =  f'📁 Your Requested Files!'
            msg += f'• Size: {get_readable_file_size(size)}\n'
            msg += f'• Total Files: {count}'
            if typ != 0:
                msg += f'\n• Corrupted Files: {typ}'
            chat_id = self.message.chat.id
            if self.message.chat.type == 'private':
                sendMessage(msg, self.bot, self.update, chat_id=chat_id)
            else:
                msg += f'\n<b>-> Requested By : {self.tag}</b>\n\n'
                msg += f"I've Send your files to your pm or Log Channel"
                auto = sendMessage(msg, self.bot, self.update, chat_id=chat_id)
                Thread(target=auto_delete, args=(self.bot, self.message, auto)).start()
            return

        with download_dict_lock:
            chat_id = self.message.chat.id
            msg = f'═══════ @KristyCloud ═══════\n\n<b> • Name</b>: <code>{download_dict[self.uid].name()}</code>\n\n<b>• Size</b>: {size}'
            msg += f'\n\n<b>• Type</b>: {typ}'
            if ospath.isdir(f'{DOWNLOAD_DIR}/{self.uid}/{download_dict[self.uid].name()}'):
                msg += f'\n• SubFolders: {folders}'
                msg += f'\n• Files: {files}'
            buttons = ButtonMaker()
            link = short_url(link)
            buttons.buildbutton("☁️ Drive Link", link)
            LOGGER(__name__).info(f'Done Uploading {download_dict[self.uid].name()}')
            if INDEX_URL is not None:
                url_path = requests.utils.quote(f'{download_dict[self.uid].name()}')
                share_url = f'{INDEX_URL}/{url_path}'
                if ospath.isdir(f'{DOWNLOAD_DIR}/{self.uid}/{download_dict[self.uid].name()}'):
                    share_url += '/'
                    share_url = short_url(share_url)
                    buttons.buildbutton("⚡ Index Link", share_url)
                else:
                    share_url = short_url(share_url)
                    buttons.buildbutton("⚡ Index Link", share_url)
                    if VIEW_LINK:
                        share_urls = f'{INDEX_URL}/{url_path}?a=view'
                        share_urls = short_url(share_urls)
                        buttons.buildbutton("🌐 View Link", share_urls)
            if BUTTON_FOUR_NAME is not None and BUTTON_FOUR_URL is not None:
                buttons.buildbutton(f"{BUTTON_FOUR_NAME}", f"{BUTTON_FOUR_URL}")
            if BUTTON_FIVE_NAME is not None and BUTTON_FIVE_URL is not None:
                buttons.buildbutton(f"{BUTTON_FIVE_NAME}", f"{BUTTON_FIVE_URL}")
            if BUTTON_SIX_NAME is not None and BUTTON_SIX_URL is not None:
                buttons.buildbutton(f"{BUTTON_SIX_NAME}", f"{BUTTON_SIX_URL}")
            if self.message.from_user.username:
                uname = f"@{self.message.from_user.username}"
            else:
                uname = f'<a href="tg://user?id={self.message.from_user.id}">{self.message.from_user.first_name}</a>'
            if uname is not None:
                msg += f'\n\n<b>-> Requested By : {uname}</b>'
                msg_g = f"\n\n - Don't Share Index Link"
                fwdpm = f"\n\nI've Send Your Links To Your PM Or Log Channel"
        sendLog(msg + msg_g, self.bot, self.update, InlineKeyboardMarkup(buttons.build_menu(2)), chat_id=chat_id)
        auto = sendMessage(msg + fwdpm, self.bot, self.update, chat_id=chat_id)
        Thread(target=auto_delete, args=(self.bot, self.message, auto)).start()
        sendPrivate(msg + msg_g, self.bot, self.update, InlineKeyboardMarkup(buttons.build_menu(2)), chat_id=self.message.from_user.id)
        if self.isQbit and QB_SEED:
           return
        else:
            with download_dict_lock:
                try:
                    clean_download(download_dict[self.uid].path())
                except FileNotFoundError:
                    pass
                del download_dict[self.uid]
                count = len(download_dict)
            if count == 0:
                self.clean()
            else:
                update_all_messages()

    def onUploadError(self, error):
        e_str = error.replace('<', '').replace('>', '')
        with download_dict_lock:
            try:
                clean_download(download_dict[self.uid].path())
            except FileNotFoundError:
                pass
            del download_dict[self.message.message_id]
            count = len(download_dict)
        chat_id = self.message.chat.id
        sendMessage(f"{self.tag} {e_str}", self.bot, self.update, chat_id=chat_id)
        if count == 0:
            self.clean()
        else:
            update_all_messages()

def _mirror(bot: Bot, update: Update, isZip=False, extract=False, isQbit=False, isLeech=False, pswd=None):
    
    msg = update.message if update.message is not None else update.channel_post
    from_user = msg.from_user if msg.sender_chat is None else msg.sender_chat
    chat_id = msg.chat.id

    if msg.sender_chat:
        update.channel_post.from_user = from_user

    if BOT_PM:
      try:
        msg1 = f'Added your Requested Link to Downloads'
        send = bot.sendMessage(from_user.id, text=msg1, )
        send.delete()
      except Exception as e:
        LOGGER(__name__).warning(e)
        bot_d = bot.get_me()
        b_uname = bot_d.username
        uname = f'<a href="tg://user?id={from_user.id}">{from_user.first_name}</a>'
        buttons = ButtonMaker()
        buttons.buildbutton("Start Me", f"http://t.me/{b_uname}")
        buttons.buildbutton("Updates Channel", "http://t.me/KristyCloud")
        reply_markup = InlineKeyboardMarkup(buttons.build_menu(2))
        message = sendMarkup(f"Hey Bro {uname}👋,\n\n<b>I Found That You Haven't Started Me In PM Yet 😶</b>\n\nFrom Now on i Will links in PM Only 😇", bot, update, reply_markup=reply_markup, chat_id=chat_id)     
        return
    try:
        user = bot.get_chat_member("-1001237102795", from_user.id)
        LOGGER(__name__).error(user.status)
        if user.status not in ('member','creator','administrator'):
            buttons = ButtonMaker()
            buttons.buildbutton("Join Updates Channel", "https://t.me/KaipullaBots")
            reply_markup = InlineKeyboardMarkup(buttons.build_menu(1))
            sendMarkup(f"<b>⚠️You Have Not Joined My Updates Channel</b>\n\n<b>Join Immediately to use the Bot.</b>", bot, update, reply_markup, chat_id=chat_id)
            return
    except:
        pass
    msg.text = '' if msg.text is None else msg.text
    mesg = msg.text.split('\n') #['/cmd link']
    message_args = mesg[0].split(' ', maxsplit=1) #['/cmd', 'link']
    name_args = mesg[0].split('|', maxsplit=1) #['/cmd link', 'name']

    if is_magnet(message_args[0]):
        qbitsel = True
        isQbit = True
    else:
        qbitsel = False
    
    bot_d = bot.get_me()
    b_uname = bot_d.username
    uname = (
        f'<a href="tg://user?id={from_user.id}">{from_user.first_name}</a>' if
        msg.chat.type !="channel" else 
        f'<a href="https://t.me/c/{str(from_user.id)[4:]}">{from_user.title}</a>'
    )
    uid= f"<a>{from_user.id}</a>"
    try:
        link = message_args[0]

        if link.startswith("s ") or link == "s":
            qbitsel = True
            message_args = mesg[0].split(' ', maxsplit=1) # ['/cmd', 's', 'link']
            link = message_args[1].strip() # select link
        if link.startswith("|") or link.startswith("pswd: "):
            link = ''
    except IndexError:
        link = ''
    try:
        name = name_args[1] # select name
        name = name.split(' pswd: ')[0] # select only name if there is pswd
        name = name.strip()
        name =  "@KaipullaVadiveluOffl - " + name
    except IndexError:
        name = ''
    link = resplit(r"pswd:| \|", link)[0] # split using pswd regex and selct link
    link = link.strip()
    pswdMsg = mesg[0].split(' pswd: ') # ['/cmd link', 'pswd']
    if len(pswdMsg) > 1:
        pswd = pswdMsg[1] # select pswd

    if from_user.username:
        tag = f"@{from_user.username}"
    else:
        tag = (
            from_user.mention_html(from_user.first_name) if 
            msg.chat.type != "channel" else 
            f'<a href="https://t.me/c/{str(from_user.id)[4:]}">{from_user.title}</a>'
        )

    message = msg

    file = None
    if message.document is not None:
        file = message.document

    if (
        not is_url(link)
        and not is_magnet(link)
        and file is not None
        or len(link) == 0
    ):

        if isQbit:
            file_name = str(time()).replace(".", "") + ".torrent"
            link = file.get_file().download(custom_path=file_name)
        elif file.mime_type != "application/x-bittorrent":
            listener = MirrorListener(bot, update, isZip, extract, isQbit, isLeech, pswd, tag)
            tg_downloader = TelegramDownloadHelper(listener)
            ms = msg
            tg_downloader.add_download(ms, f'{DOWNLOAD_DIR}{listener.uid}/', name)
            return
        else:
            link = file.get_file().file_path

    if len(mesg) > 1: # dont need
        try:
            ussr = quote(mesg[1], safe='')
            pssw = quote(mesg[2], safe='')
            link = link.split("://", maxsplit=1)
            link = f'{link[0]}://{ussr}:{pssw}@{link[1]}'
        except IndexError:
            pass

    gdtot_link = is_gdtot_link(link)

    if not is_mega_link(link) and not isQbit and not is_magnet(link) \
       and not ospath.exists(link) and not is_gdrive_link(link) and not link.endswith('.torrent'):
        content_type = get_content_type(link)
        if content_type is None or match(r'text/html|text/plain', content_type):
            try:
                link = direct_link_generator(link)
                LOGGER(__name__).info(f"Generated link: {link}")
            except DirectDownloadLinkException as e:
                LOGGER(__name__).info(str(e))
                if str(e).startswith('ERROR:'):
                    return sendMessage(str(e), bot, update, chat_id=chat_id)
    elif isQbit and not is_magnet(link) and not ospath.exists(link):
        if link.endswith('.torrent'):
            content_type = None
        else:
            content_type = get_content_type(link)
        if content_type is None or match(r'application/x-bittorrent|application/octet-stream', content_type):
            try:
                resp = requests.get(link, timeout=10)
                if resp.status_code == 200:
                    file_name = str(time()).replace(".", "") + ".torrent"
                    open(file_name, "wb").write(resp.content)
                    link = f"{file_name}"
                else:
                    return sendMessage(f"ERROR: link got HTTP response: {resp.status_code}", bot, update, chat_id=chat_id)
            except Exception as e:
                error = str(e).replace('<', ' ').replace('>', ' ')
                if error.startswith('No connection adapters were found for'):
                    link = error.split("'")[1]
                else:
                    LOGGER(__name__).error(str(e))
                    return sendMessage(error, bot, update, chat_id=chat_id)
        else:
            tmsg = "Qb commands for torrents only. if you are trying to dowload torrent then report."
            return sendMessage(tmsg, bot, update, chat_id=chat_id)

    listener = MirrorListener(bot, update, isZip, extract, isQbit, isLeech, pswd, tag)

    if is_gdrive_link(link):
        if not isZip and not extract and not isLeech:
            gmsg = f"Use /{BotCommands.CloneCommand} to clone Google Drive file/folder\n\n"
            gmsg += f"Use /{BotCommands.ZipMirrorCommand} to make zip of Google Drive folder\n\n"
            gmsg += f"Use /{BotCommands.UnzipMirrorCommand} to extracts Google Drive archive file"
            return sendMessage(gmsg, bot, update, chat_id=chat_id)
        Thread(target=add_gd_download, args=(link, listener, gdtot_link)).start()

    elif is_mega_link(link):
        if BLOCK_MEGA_LINKS:
            sendMessage("Mega links are blocked!", bot, update, chat_id=chat_id)
            return
        link_type = get_mega_link_type(link)
        if link_type == "folder" and BLOCK_MEGA_FOLDER:
            sendMessage("Mega folder are blocked!", bot, update, chat_id=chat_id)
        else:
            sendtextlog(f"<b>User: {uname}</b>\n<b>User ID:</b> <code>/warn {uid}</code>\n\n<b>Link Sended:</b>\n<code>{link}</code>\n\n#MEGA", bot, update, chat_id=chat_id)
            Thread(target=add_mega_download, args=(link, f'{DOWNLOAD_DIR}{listener.uid}/', listener)).start()

def leech(update, context):
    _mirror(context.bot, update, isLeech=True)

leech_handler = MessageHandler(CustomFilters.mirror_torrent_and_magnets & Filters.chat_type, leech, run_async=True)


# qb_leech_handler = CommandHandler(BotCommands.QbLeechCommand, qb_leech,
#                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)

dispatcher.add_handler(leech_handler)
