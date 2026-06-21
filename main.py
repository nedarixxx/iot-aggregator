import os
import time
import requests
import html
import re
from dotenv import load_dotenv

load_dotenv()

# БЛОК НАСТРОЕК 
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHANNEL = os.getenv("TG_CHANNEL")
VK_TOKEN = os.getenv("VK_TOKEN")

# СПИСОК ГРУПП ДЛЯ ОТСЛЕЖИВАНИЯ ПОСТОВ
VK_GROUPS = {
    226921338: "Второй курс ИОТ, УрФУ",
    188533997: "Проектный практикум ИРИТ-РТФ",
    230634931: "Поселение ИРИТ-РТФ УрФУ",
}

# ID ГРУППЫ, С КОТОРОЙ НУЖНО ВЗЯТЬ АВАТАРКУ ПРИ ЗАПУСКЕ
AVATAR_TRACK_GROUP_ID = 226921338  

CHECK_INTERVAL = 600  # Время круга проверки (В секундах)


def get_last_saved_id(group_id):
    """Читает ID последнего обработанного поста для конкретной группы."""
    filename = f"last_post_{group_id}.txt"
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try:
                return int(f.read().strip())
            except ValueError:
                return 0
    return 0


def save_last_id(group_id, post_id):
    """Сохраняет ID последнего поста для конкретной группы."""
    filename = f"last_post_{group_id}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(str(post_id))


def set_initial_avatar():
    """Единожды устанавливает аватарку в ТГ при запуске скрипта."""
    if not AVATAR_TRACK_GROUP_ID:
        return

    print(f"Загружаю стартовую аватарку из группы ID: {AVATAR_TRACK_GROUP_ID}...")
    vk_group_url = "https://api.vk.com/method/groups.getById"
    group_params = {
        "group_id": AVATAR_TRACK_GROUP_ID,
        "fields": "photo_200",
        "access_token": VK_TOKEN,
        "v": "5.131"
    }
    
    try:
        group_res = requests.get(vk_group_url, params=group_params).json()
        if "response" in group_res and len(group_res["response"]) > 0:
            current_avatar_url = group_res["response"][0].get("photo_200")
            
            if current_avatar_url:
                photo_res = requests.get(current_avatar_url)
                if photo_res.status_code == 200:
                    url = f"https://api.telegram.org/bot{TG_TOKEN}/setChatPhoto"
                    files = {'photo': ('avatar.jpg', photo_res.content, 'image/jpeg')}
                    payload = {'chat_id': TG_CHANNEL}
                    tg_res = requests.post(url, data=payload, files=files)
                    
                    if tg_res.status_code == 200:
                        print("✅ Стартовая аватарка канала успешно установлена!")
                    else:
                        print(f"❌ Ошибка установки аватарки в ТГ: {tg_res.text}")
    except Exception as e:
        print(f"⚠️ Не удалось установить аватарку при запуске: {e}")


def fix_vk_links_and_html(vk_text):
    """Очищает текст от багов разметки ВК и превращает их в понятные для ТГ ссылки."""
    if not vk_text:
        return ""
    text = html.escape(vk_text)
    text = re.sub(r'\[#alias\|([^|]+)\|([^\]]+)\]', r'<a href="\2">\1</a>', text)
    text = re.sub(r'\[(club|id)(\d+)\|([^\]]+)\]', r'<a href="https://vk.com/\1\2">\3</a>', text)
    return text


def send_to_telegram(text, post_url, photo_url=None):
    """Отправляет пост в Телеграм канал с кнопкой-ссылкой и фото НАВЕРХУ."""
    if photo_url and len(text) > 1024:
        text = f'<a href="{photo_url}">\u200b</a>{text}'
        photo_url = None  

    # Формируем клавиатуру с одной кнопкой-ссылкой
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🔗 Оригинал поста", "url": post_url}
            ]
        ]
    }

    if photo_url:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
        payload = {
            "chat_id": TG_CHANNEL,
            "photo": photo_url,
            "caption": text,
            "parse_mode": "HTML",
            "reply_markup": reply_markup  # Добавляем кнопку к фото
        }
    else:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {
            "chat_id": TG_CHANNEL,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {
                "show_above_text": True,      
                "prefer_large_media": True    
            },
            "reply_markup": reply_markup  # Добавляем кнопку к тексту
        }

    response = requests.post(url, json=payload)
    return response.status_code == 200


def check_vk_wall(group_id, group_name):
    """Проверяет стену конкретного сообщества (ТОЛЬКО ПОСТЫ)."""
    print(f"Проверяю сообщество: {group_name} (ID: {group_id})...")
    owner_id = -abs(group_id)

    vk_url = "https://api.vk.com/method/wall.get"
    params = {
        "owner_id": owner_id,
        "count": 3,  
        "access_token": VK_TOKEN,
        "v": "5.131",
    }

    try:
        res = requests.get(vk_url, params=params).json()
        if "error" in res:
            print(f"[Ошибка VK API для группы {group_id}]: {res['error']['error_msg']}")
            return
        posts = res["response"]["items"]
    except Exception as e:
        print(f"Ошибка запроса постов для группы {group_id}: {e}")
        return

    last_saved_id = get_last_saved_id(group_id)
    new_posts = []

    for post in posts:
        if "id" not in post:
            continue
            
        if post.get("is_pinned") and last_saved_id != 0 and post["id"] <= last_saved_id:
            continue
            
        if post["id"] > last_saved_id:
            new_posts.append(post)

    if not new_posts:
        print(f"Новых постов в группе {group_name} нет.")
        return

    new_posts.sort(key=lambda x: x["date"])

    for post in new_posts:
        vk_text = post.get("text", "")
        photo_url = None

        if "attachments" in post:
            for attach in post["attachments"]:
                if attach["type"] == "photo":
                    sizes = attach["photo"]["sizes"]
                    largest_photo = max(sizes, key=lambda x: x["width"] * x["height"])
                    photo_url = largest_photo["url"]
                    break

        clean_text = fix_vk_links_and_html(vk_text)

        source_url = f"https://vk.com/wall{owner_id}_{post['id']}"
        header = f'Источник: <b>{group_name}</b>\n\n' # Убрал ссылку из текста, так как теперь есть кнопка
        full_text = header + clean_text

        if len(full_text) > 4090:
            full_text = full_text[:4087] + "..."

        print(f"Отправляю пост #{post['id']} из группы {group_name}...")
        
        # Передаем source_url вторым аргументом для создания кнопки
        success = send_to_telegram(full_text, source_url, photo_url)

        if success:
            if post["id"] > last_saved_id:
                last_saved_id = post["id"]
                save_last_id(group_id, last_saved_id)
            time.sleep(3)
        else:
            print(f"Не удалось отправить пост #{post['id']}.")
            break


def main():
    print("Бот-агрегатор мульти-групп запущен и готов к работе!")
    
    # 1. Единожды ставим аватарку при старте
    set_initial_avatar()

    # 2. Запускаем бесконечный цикл мониторинга постов
    while True:
        for group_id, group_name in VK_GROUPS.items():
            try:
                check_vk_wall(group_id, group_name)
            except Exception as e:
                print(f"Критический сбой при обработке группы {group_name}: {e}")
            time.sleep(5)  
            
        print(f"Все группы проверены. Ожидание {CHECK_INTERVAL} секунд...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()