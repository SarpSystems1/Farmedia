import os
from openai import OpenAI
from dotenv import load_dotenv

# .env dosyasındaki değişkenleri yüklüyoruz
load_dotenv()

# OpenAI istemcisini başlatıyoruz
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def get_sarp_ai_advice(question: str, weather_context: str = "") -> str:
    """
    Sarp AI ziraî danışmanlık servisi.
    Kullanıcının sorusunu ve opsiyonel hava/don verilerini alarak profesyonel yanıt üretir.
    """
    try:
        system_prompt = (
            "Sen Farmedia projesinin uzman ziraat mühendisi ve yapay zeka danışmanı Sarp AI'sın. "
            "Çiftçilere ve tarımla ilgilenenlere net, pratik, bilimsel ve anlaşılır tavsiyeler verirsin. "
            "Eğer sana anlık hava veya don analizi verisi verilmişse, yanıtlarını bu verilerle harmanlayarak "
            "nokta atışı önerilerde bulun."
        )

        user_content = f"Soru: {question}"
        if weather_context:
            user_content += f"\n\nAnlık Tarım/Hava Verisi Bağlamı:\n{weather_context}"

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.7,
            max_tokens=500
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"Sarp AI şu anda yanıt üretemiyor. Hata: {str(e)}"