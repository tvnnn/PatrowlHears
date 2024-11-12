import requests
import logging
logger = logging.getLogger(__name__)

def send_message(bot_token, chat_id, message):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        if '_' in chat_id:
            chat_id, message_thread_id = chat_id.split('_')
            payload = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'Markdown',
                'message_thread_id': int(message_thread_id)
            }
        else:
            chat_id = chat_id
            payload = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
        requests.post(url, json=payload)
        return True
    except Exception as e:
        logger.error(f"Got an error: {str(e)}")
        return False
        