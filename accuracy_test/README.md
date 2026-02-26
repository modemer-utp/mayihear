# MayiHear — Script de Precisión de Transcripción

Compara la transcripción de MayiHear contra subtítulos de referencia usando
**WER** (Word Error Rate) y **CER** (Character Error Rate) — las métricas
estándar de la industria para sistemas ASR (reconocimiento de voz).

---

## Instalación

```bash
cd accuracy_test
pip install -r requirements.txt
```

---

## Uso

```bash
python compare.py --reference subtitles.txt --hypothesis mayihear.txt
```

Con guardado de reporte JSON en `results/`:

```bash
python compare.py --reference subtitles.txt --hypothesis mayihear.txt --save
```

### Argumentos

| Argumento | Descripción |
|---|---|
| `--reference` / `-r` | Transcripción de referencia (verdad de tierra) |
| `--hypothesis` / `-y` | Transcripción generada por MayiHear |
| `--save` / `-s` | Guarda reporte JSON en `accuracy_test/results/` |

---

## Cómo obtener subtítulos de referencia

### Opción A — YouTube con yt-dlp

1. Instala yt-dlp: `pip install yt-dlp`

2. Descarga subtítulos automáticos en español:
   ```bash
   yt-dlp --write-auto-subs --sub-lang es --skip-download <URL_DEL_VIDEO>
   ```

3. Convierte el archivo `.vtt` a texto plano:
   ```bash
   # Elimina cabeceras VTT y timestamps
   grep -v "^WEBVTT" subtitles.es.vtt | grep -v "^[0-9]" | grep -v "^$" | grep -v "-->" > reference.txt
   ```
   O puedes usar Python:
   ```python
   import re
   with open("subtitles.es.vtt", encoding="utf-8") as f:
       content = f.read()
   # Elimina timestamps y cabeceras
   content = re.sub(r"WEBVTT.*?\n\n", "", content, flags=re.DOTALL)
   content = re.sub(r"\d+:\d+:\d+\.\d+ --> .*\n", "", content)
   content = re.sub(r"\n{2,}", "\n", content).strip()
   with open("reference.txt", "w", encoding="utf-8") as f:
       f.write(content)
   ```

4. Graba el mismo video con MayiHear y guarda la transcripción como `mayihear.txt`.

---

## Fuentes de contenido recomendadas para pruebas

Para obtener resultados representativos del caso de uso UTP (reuniones en español),
usa contenido de **30 a 60 minutos** de duración. Ordenadas de mayor a menor
calidad de subtítulos:

### 1. TED Talks en Español (YouTube)
- **Por qué:** Subtítulos revisados por humanos, la calidad de referencia más alta.
- **Duración:** 15–18 min por charla — usa 2–3 seguidas para tener 30–60 min.
- **Cómo:** Busca "TED en Español" en YouTube y descarga con `--sub-lang es`.
- **Recomendado para comenzar.**

### 2. RPP Noticias — Entrevistas (YouTube / rpp.pe)
- **Por qué:** Acento peruano, el más cercano al usuario final (UTP Lima).
- **Duración:** Entrevistas de 30–60 min disponibles.
- **Nota:** Subtítulos automáticos — verificar manualmente antes de usar como referencia.

### 3. Canal N Peru — Entrevistas y debates
- **Por qué:** Acento local peruano, formato de conversación similar a reuniones.
- **Duración:** Segmentos de 30–60 min.

### 4. CNN en Español — Entrevistas
- **Por qué:** Español neutro y claro, subtítulos disponibles.
- **Duración:** Entrevistas de 30–60 min.

### 5. RTVE La 2 — Documentales (Spain)
- **Por qué:** Español de España, subtítulos cerrados (CC) de alta calidad.
- **Duración:** Documentales de 50–60 min con CC preciso.
- **Nota:** Acento diferente al peruano — útil como prueba de generalización.

---

## Interpretación de resultados WER

| WER | Calificación |
|---|---|
| < 10% | Excelente |
| 10–20% | Bueno |
| 20–35% | Aceptable |
| > 35% | Necesita mejora |

Los sistemas ASR modernos (incluyendo Whisper) suelen lograr WER de 5–15%
en español con audio limpio. El audio de loopback de sistema es muy limpio
(sin ruido de sala), por lo que se esperan resultados en el rango excelente/bueno.

---

## Workflow típico de prueba

```bash
# 1. Elige un video de referencia (ej: TED Talk en Español, 15 min)
yt-dlp --write-auto-subs --sub-lang es --skip-download https://youtu.be/XXXX

# 2. Convierte VTT a texto plano
python -c "
import re
with open('video.es.vtt', encoding='utf-8') as f: c = f.read()
c = re.sub(r'WEBVTT.*?\n\n', '', c, flags=re.DOTALL)
c = re.sub(r'\d+:\d+:\d+\.\d+ --> .*\n', '', c)
c = re.sub(r'\n{2,}', '\n', c).strip()
open('reference.txt', 'w', encoding='utf-8').write(c)
"

# 3. Reproduce el video en tu PC y graba con MayiHear
# 4. Copia la transcripción de MayiHear a mayihear.txt

# 5. Compara
python compare.py --reference reference.txt --hypothesis mayihear.txt --save
```
