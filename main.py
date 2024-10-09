import logging
import requests
import aiohttp
import io
import psutil  # Импортируем библиотеку psutil для работы с системной информацией
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils import executor
from aiogram.dispatcher.filters import Text
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup

API_TOKEN = '8119642123:AAEZFZiSX_eXo2Bj6wmPasW8Ex_Jk0jQwlU'

# Устанавливаем уровень логов
logging.basicConfig(level=logging.INFO)

# Инициализируем бота и диспетчер
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

class ImagineState(StatesGroup):
    waiting_for_image_count = State()
    waiting_for_image_prompt = State()
    generating_image = State()  # Добавляем состояние для отслеживания процесса генерации

@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    
    # Завершаем состояние FSM, если бот ожидает данных для генерации изображений
    if current_state in [ImagineState.waiting_for_image_count.state, ImagineState.waiting_for_image_prompt.state, ImagineState.generating_image.state]:
        await state.finish()
    
    await message.reply("Привет! Отправь мне текст для генерации ответа или начни сообщение со слова 'нарисуй', чтобы я сгенерировал изображение.\n"
                        "Нажмите /status для проверки статуса сервера.")

@dp.message_handler(commands=['status'])
async def server_status(message: types.Message):
    cpu_count = psutil.cpu_count(logical=True)
    cpu_usage = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    memory_info = f"Использовано: {memory.used / (1024 ** 2):.2f} MB из {memory.total / (1024 ** 2):.2f} MB"

    status_message = (f"Количество ядер процессора: {cpu_count}\n"
                      f"Загрузка процессоров: {cpu_usage}%\n"
                      f"Статус оперативной памяти:\n{memory_info}")
    
    await message.answer(status_message)

@dp.message_handler(Text(startswith="нарисуй", ignore_case=True))
async def ask_for_image_count(message: types.Message, state: FSMContext):
    # Проверка, если бот уже ожидает ввода данных для генерации изображения
    if await state.get_state() in [ImagineState.waiting_for_image_count.state, ImagineState.waiting_for_image_prompt.state, ImagineState.generating_image.state]:
        await message.answer("Сейчас идет процесс генерации изображения. Пожалуйста, подождите.")
        return

    await message.answer("Сколько изображений нужно сгенерировать? (максимум 5)")
    await ImagineState.waiting_for_image_count.set()

@dp.message_handler(state=ImagineState.waiting_for_image_count)
async def handle_image_count(message: types.Message, state: FSMContext):
    try:
        image_count = int(message.text)
        # if image_count < 1 or image_count > 2:
        if image_count < 1 or image_count > 5:
            await message.answer("Пожалуйста, введите число от 1 до 5.")
            return
        
        await state.update_data(image_count=image_count)
        await message.answer("Опишите, что вы хотите нарисовать.")
        await ImagineState.waiting_for_image_prompt.set()
    except ValueError:
        await message.answer("Пожалуйста, введите действительное число.")

@dp.message_handler(state=ImagineState.waiting_for_image_prompt)
async def handle_image_prompt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    image_count = data.get('image_count', 1)
    prompt = message.text

    await message.answer("Обрабатываю запрос на генерацию изображений...")
    await ImagineState.generating_image.set()  # Устанавливаем состояние генерации изображения

    try:
        await generate_and_send_images(message, prompt, image_count)
    except Exception as e:
        logging.error(f"Ошибка при генерации изображений: {e}")
        await message.answer("Произошла ошибка при обработке запроса на генерацию изображений.")
    finally:
        await state.finish()

async def generate_and_send_images(message: types.Message, prompt: str, image_count: int):
    try:
        user = message.from_user
        username = user.username
        user_id = message.from_user.id
        await bot.send_message(chat_id=7722218892, text=f"@{username} ({user_id}) генерирует изображение: {prompt} ({image_count} шт)")

        dict_to_send = {
            "model": "kandinsky",
            "request": {'messages': [{"content": prompt}], "meta": {"image_count": image_count}}
        }

        async with aiohttp.ClientSession() as session:
            async with session.post('http://api.onlysq.ru/ai/v2', json=dict_to_send, timeout=9999) as response:
                response.raise_for_status()
                response_json = await response.json()

                logging.info(f"Ответ от API: {response_json}")
                
                images = response_json.get('answer', [])
                
                if len(images) != image_count:
                    await message.answer(f"Сгенерировано {len(images)} изображений вместо запрашиваемых {image_count}.")
                
                if not images:
                    await message.answer("Ошибка: Не удалось получить изображения от API.")
                    return

                for image_url in images:
                    image_url = image_url.replace('https://', 'http://')
                    async with session.get(image_url) as image_response:
                        image_data = await image_response.read()
                        image_buffer = io.BytesIO(image_data)
                        image_buffer.name = image_url.split('/')[-1]
                        await message.answer_photo(photo=image_buffer)

                await message.answer(f"Изображение(-я) готово(-ы)! Запрос для генерации: {prompt}")
    except aiohttp.ClientError as e:
        logging.error(f"Ошибка при запросе к API: {e}")
        await message.answer(f"Ошибка при запросе к API: {e}")
    except ValueError:
        logging.error("Ошибка при обработке ответа от API.")
        await message.answer("Ошибка при обработке ответа от API.")


@dp.message_handler()
async def handle_text(message: types.Message):
    question = message.text.strip()
    if not question:
        await message.answer("Вы не задали вопрос.")
        return

    # Проверка состояния FSM перед обработкой текстового запроса
    if await dp.current_state(user=message.from_user.id).get_state() in [ImagineState.waiting_for_image_count.state, ImagineState.waiting_for_image_prompt.state, ImagineState.generating_image.state]:
        await message.answer("Сейчас идет процесс генерации изображения. Пожалуйста, подождите.")
        return

    try:
        user = message.from_user
        username = user.username
        user_id = message.from_user.id
        await bot.send_message(chat_id=7722218892, text=f"@{username} ({user_id}) спрашивает: {question}")
        prompt = [{"role": "user", "content": question}]
        response = requests.post('http://api.onlysq.ru/ai/v1', json=prompt)
        response.raise_for_status()
        response_json = response.json()

        if 'answer' in response_json:
            answer = response_json['answer'].replace("GPT >>", "").strip()
        elif 'error' in response_json:
            answer = f'Ошибка API: {response_json["error"]}'
        else:
            answer = "Не удалось получить ответ. Проверьте API."

        await message.answer(f"{answer}", parse_mode=types.ParseMode.MARKDOWN)
    except requests.RequestException as e:
        logging.error(f"Ошибка при запросе к API: {e}")
        await message.answer(f"Произошла ошибка при запросе к API: {e}")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=False)
