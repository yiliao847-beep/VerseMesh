import streamlit as st
import streamlit.components.v1 as components
import os
import json
import re
import base64
from dotenv import load_dotenv
from zhipuai import ZhipuAI
from zhipuai.core._errors import APIAuthenticationError, APIStatusError
import time
import random
from datetime import datetime
from urllib import request as urllib_request
from urllib import error as urllib_error
import html

# ==================== 初始化配置 ====================
load_dotenv()

# 检查环境变量
api_key = os.getenv("ZHIPUAI_API_KEY", "").strip().strip('"').strip("'")
model_name = os.getenv("ZHIPUAI_MODEL_NAME", "glm-4-plus")
bailian_api_key = os.getenv("BAILIAN_API_KEY", "").strip().strip('"').strip("'")
image_model_name = os.getenv("WAN_IMAGE_MODEL_NAME", "wan2.7-image-pro")
wan_base_url = os.getenv("WAN_BASE_URL", "https://dashscope.aliyuncs.com/api/v1").strip().rstrip("/")

if not api_key:
    st.error("错误：未在 .env 文件中找到 ZHIPUAI_API_KEY")
    st.info("请创建 .env 文件并添加你的智谱API密钥")
    st.code("""
    # .env 文件内容示例：
    ZHIPUAI_API_KEY=your_actual_api_key_here
    ZHIPUAI_MODEL_NAME=glm-4-plus
    """)
    st.stop()

if api_key == "your_api_key_here":
    st.error("错误：请将 .env 中的 ZHIPUAI_API_KEY 替换为真实密钥")
    st.stop()

# 初始化智谱客户端
client = ZhipuAI(api_key=api_key)

# 会话状态初始化，避免 Streamlit 重跑后丢失结果
if "compiled_result" not in st.session_state:
    st.session_state.compiled_result = None
if "compiled_input_text" not in st.session_state:
    st.session_state.compiled_input_text = ""
if "generated_image_url" not in st.session_state:
    st.session_state.generated_image_url = None
if "last_image_prompt" not in st.session_state:
    st.session_state.last_image_prompt = ""
if "last_image_meta" not in st.session_state:
    st.session_state.last_image_meta = {}
if "verse_input" not in st.session_state:
    st.session_state.verse_input = ""
# vm_*：可玩小功能状态（不替代 verse_input 等核心键）
if "vm_last_poem_pick" not in st.session_state:
    st.session_state.vm_last_poem_pick = ""
if "vm_balloons_next_image" not in st.session_state:
    st.session_state.vm_balloons_next_image = False

# 页脚文言短签（按公历日取模，同日稳定、不重跑乱跳）
_VM_FOOTER_SIGS = (
    "辞气声韵，可寄千载。",
    "纸短情长，意在象先。",
    "以字为境，化意为象。",
    "片言居要，万象森罗。",
    "文心一点，画意千寻。",
    "静观默会，迁想妙得。",
    "不著一字，尽得风流。",
    "羚羊挂角，无迹可求。",
)


def _vm_hint(text: str) -> None:
    """古风提示条（替代默认 st.info 紫框）。文本经 HTML 转义。"""
    st.markdown(
        '<div class="vm-hint" role="status"><div class="vm-hint-inner">'
        + html.escape(text)
        + "</div></div>",
        unsafe_allow_html=True,
    )


_VM_WAIT_TIPS_COMPILE = (
    "即墨初研，静待锋毫。",
    "纸窗竹影，句读徐行。",
    "迁想妙得，正在会意。",
    "片言居要，万象将生。",
    "静观默会，莫急成章。",
)

_VM_WAIT_TIPS_IMAGE = (
    "丹青在腕，烟云欲渡。",
    "皴擦未干，且听风吟。",
    "咫尺千里，意象将显。",
    "墨晕初开，稍候片时。",
    "意在笔先，画随诗至。",
)


def _vm_wait_curtain_html(mode: str) -> str:
    """全页等待时轻量古风幕：小印旋转 + 轮换短句；行首勿≥4 空格。"""
    tips = _VM_WAIT_TIPS_COMPILE if mode == "compile" else _VM_WAIT_TIPS_IMAGE
    idx = int(time.time()) % len(tips)
    tip = html.escape(tips[idx])
    title = "钤印会意" if mode == "compile" else "丹青将成"
    return (
        f'<div class="vm-wait-curtain vm-wait-curtain--{mode}" role="status" aria-live="polite">'
        f'<span class="vm-wait-seal" aria-hidden="true">印</span>'
        f'<span class="vm-wait-copy"><span class="vm-wait-title">{html.escape(title)}</span>'
        f'<span class="vm-wait-tip">{tip}</span></span></div>'
    )


_VM_COMPILE_SEAL_LINES = (
    "会意已钤。",
    "句读成章。",
    "墨晕初定。",
    "诗眼在兹。",
    "迁想已得。",
    "片言成境。",
)

_VM_IMAGE_DONE_LINES = (
    "丹青已成，烟云入帧。",
    "尺幅千里，意象已驻。",
    "皴擦既毕，画意可览。",
    "绢素有光，与诗相映。",
    "墨彩既施，与句相照。",
)


def _vm_random_compile_seal_line() -> str:
    return random.choice(_VM_COMPILE_SEAL_LINES)


def _vm_image_done_line(size_label: str, style_label: str) -> str:
    base = random.choice(_VM_IMAGE_DONE_LINES)
    st_cn = "鲜明" if (style_label or "").lower() == "vivid" else "自然"
    return f"{base}（{size_label}，{st_cn}）"


def _vm_clipboard_copy_button(label: str, text: str) -> None:
    """一键复制（components iframe 内 navigator.clipboard）。"""
    payload = json.dumps(text)
    safe_label = html.escape(label)
    components.html(
        f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>
body{{margin:0;font-family:system-ui,sans-serif;}}
button{{
cursor:pointer;padding:0.35rem 0.75rem;border-radius:6px;
border:1px solid rgba(196,181,154,0.85);
background:linear-gradient(165deg,#faf6ec,#e8dcc4);color:#2a2218;font-size:13px;
}}
button:hover{{filter:brightness(1.04);}}
#m{{font-size:11px;color:#5c4f42;margin:0.25rem 0 0 0;min-height:1em;}}
</style></head><body>
<button type="button" onclick="(async()=>{{try{{await navigator.clipboard.writeText({payload});
document.getElementById('m').textContent='已复制到剪贴板';}}catch(e){{document.getElementById('m').textContent='复制失败，请手动全选复制';}}}})()">{safe_label}</button>
<p id="m"></p>
</body></html>""",
        height=72,
    )


def _poetic_snippet_from_last_prompt(raw: str) -> str:
    """从 used_prompt 中摘出 [POETIC-CN] 段前约 200 字，供折叠展示。"""
    if not raw:
        return ""
    if "[POETIC-CN]" in raw:
        rest = raw.split("[POETIC-CN]", 1)[1].lstrip()
        if "\n\n[" in rest:
            rest = rest.split("\n\n[", 1)[0]
        return rest.strip()[:200]
    return raw.strip()[:200]


_VM_POEM_LOTS = (
    "春江潮水连海平，海上明月共潮生。",
    "大漠孤烟直，长河落日圆。",
    "行到水穷处，坐看云起时。",
    "众里寻他千百度，蓦然回首，那人却在，灯火阑珊处。",
    "疏影横斜水清浅，暗香浮动月黄昏。",
    "采菊东篱下，悠然见南山。",
    "欲穷千里目，更上一层楼。",
    "野旷天低树，江清月近人。",
    "空山新雨后，天气晚来秋。",
    "月落乌啼霜满天，江枫渔火对愁眠。",
    "孤舟蓑笠翁，独钓寒江雪。",
    "两岸猿声啼不住，轻舟已过万重山。",
    "接天莲叶无穷碧，映日荷花别样红。",
    "小荷才露尖尖角，早有蜻蜓立上头。",
    "人间四月芳菲尽，山寺桃花始盛开。",
    "春色满园关不住，一枝红杏出墙来。",
    "落红不是无情物，化作春泥更护花。",
    "无可奈何花落去，似曾相识燕归来。",
    "知否，知否？应是绿肥红瘦。",
    "花自飘零水自流，一种相思，两处闲愁。",
    "东风夜放花千树，更吹落、星如雨。",
    "枯藤老树昏鸦，小桥流水人家。",
    "海上生明月，天涯共此时。",
    "山气日夕佳，飞鸟相与还。",
    "会当凌绝顶，一览众山小。",
    "黄河远上白云间，一片孤城万仞山。",
    "窗含西岭千秋雪，门泊东吴万里船。",
    "姑苏城外寒山寺，夜半钟声到客船。",
    "商女不知亡国恨，隔江犹唱后庭花。",
    "东风不与周郎便，铜雀春深锁二乔。",
    "念天地之悠悠，独怆然而涕下。",
    "前不见古人，后不见来者。",
)


def _ink_preview_summary(ab, tn, ct, ds, er, ns):
    """本地墨色提要（不调 API），与滑块语义一致。"""
    ab_t = "近物" if ab < 0.38 else ("远意" if ab > 0.62 else "兼工")
    tn_t = "淡墨" if tn < 0.45 else ("焦浓" if tn > 0.75 else "相济")
    ct_t = "冷青" if ct < 0.38 else ("暖赭" if ct > 0.62 else "冷暖匀")
    ds_t = "景密" if ds < 0.38 else ("留白" if ds > 0.62 else "疏密中")
    er_t = "尚古" if er < 0.38 else ("尚今" if er > 0.62 else "借古开今")
    ns_t = "直写" if ns < 0.38 else ("隐喻" if ns > 0.62 else "情景间")
    return f"当前墨法：{ab_t} · {tn_t} · {ct_t} · {ds_t} · {er_t} · {ns_t}（抽象{ab:.2f} 张力{tn:.2f}）"


# ==================== 核心功能函数 ====================
def _extract_json_payload(raw_text):
    """从模型返回文本中尽量提取 JSON 对象。"""
    if not raw_text:
        return None

    text = raw_text.strip()
    if not text:
        return None

    # 常见情况：```json ... ```
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if code_block_match:
        text = code_block_match.group(1).strip()

    # 若仍包含额外说明，截取最外层 JSON 对象
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _get_message_text(message):
    """优先读取 content，若为空则回退到 reasoning_content。"""
    content = (getattr(message, "content", None) or "").strip()
    if content:
        return content
    return (getattr(message, "reasoning_content", None) or "").strip()


def extract_aesthetic_params(
    text_input,
    abstraction_level=0.5,
    tension_level=0.7,
    color_tendency=0.5,
    density_spacing=0.5,
    era_tone=0.5,
    narrative_symbolism=0.5,
):
    """
    调用GLM模型，将诗句/短句解析为结构化审美参数
    """
    system_prompt = """你是一个顶尖的审美参数解析专家。请将用户输入的文字意境，转化为以下JSON格式的结构化参数：
{
  "core_theme": "用2-4个词概括核心审美主题，如：开阔、孤寂、生机盎然",
  "color_palette": {
    "primary_tone": "主色调，如：清冷蓝灰调/温暖土黄色系",
    "saturation": 介于1到10之间的整数,
    "brightness": 介于1到10之间的整数
  },
  "composition": {
    "horizon_line": "构图描述，如：极低地平线，天空占比大",
    "visual_balance": "平衡感描述，如：对称稳定"
  },
  "emotional_vector": {
    "tranquility": 0到100之间的整数,
    "grandeur": 0到100之间的整数,
    "ethereality": 0到100之间的整数
  },
  "artist_reference": "可参考的艺术家或风格，如：Ansel Adams的风光摄影"
}
请确保输出仅为合法的JSON，不要有任何额外解释、标记或换行。"""
    
    user_prompt = f"""请解析以下文本的审美意象，并考虑附加参数：

文本：「{text_input}」

附加控制参数：
- 抽象程度：{abstraction_level} (0=具象, 1=抽象)
- 视觉张力：{tension_level} (0=柔和, 1=强烈)
- 色彩倾向：{color_tendency} (0=偏冷色/低饱和, 1=偏暖色/饱和更高)
- 疏密留白：{density_spacing} (0=信息较满、少留白, 1=疏朗、留白多)
- 古意当代：{era_tone} (0=古雅传统气质, 1=当代感表达)
- 叙事象征：{narrative_symbolism} (0=偏直白场景, 1=偏象征隐喻)"""
    
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=1500
        )
        result_text = _get_message_text(response.choices[0].message)
        parsed = _extract_json_payload(result_text)
        if parsed is not None:
            return parsed
        raise json.JSONDecodeError("无法从模型返回中提取合法JSON对象", result_text, 0)
    except json.JSONDecodeError as e:
        st.error(f"解析模型返回的JSON时出错：{e}")
        st.code(result_text if 'result_text' in locals() and result_text else "（模型返回为空）", language="text")
        _vm_hint("建议把模型先切换为 glm-4-plus 再试；若仍失败，可降低输入长度，或点击“测试连接”确认基础调用稳定。")
        return None
    except APIAuthenticationError:
        st.error("调用API时发生错误：401 身份验证失败（API Key 无效、过期或已被禁用）")
        _vm_hint("请检查 .env 中 ZHIPUAI_API_KEY 是否正确，确认没有多余空格/引号，并在智谱开放平台重新生成密钥后重试。")
        return None
    except APIStatusError as e:
        st.error(f"调用API时发生状态错误：{e}")
        _vm_hint("可能是模型权限、额度或请求参数问题。建议先点击“测试连接”确认账号与模型可用。")
        return None
    except Exception as e:
        st.error(f"调用API时发生错误：{e}")
        return None

def generate_midjourney_prompt(params):
    """根据审美参数生成Midjourney提示词"""
    if not params:
        return ""
    
    theme = params.get("core_theme", "epic landscape")
    color = params.get("color_palette", {}).get("primary_tone", "cinematic color grading")
    composition = params.get("composition", {}).get("horizon_line", "wide angle")
    artist = params.get("artist_reference", "Ansel Adams")
    
    prompt = f"""/imagine prompt: {theme}, {color}, {composition}, by {artist}, artstation, 4k, detailed, masterpiece --ar 16:9 --style raw"""
    return prompt


def _style_axes_prompt_fragments(
    color_tendency=0.5,
    density_spacing=0.5,
    era_tone=0.5,
    narrative_symbolism=0.5,
):
    """将侧栏四轴 0~1 映射为短中文/英文描述，写入编译与出图提示；中间值 0.5 附近保持中性、接近旧版行为。"""
    if color_tendency <= 0.38:
        ct_zh, ct_en = "色彩偏冷、饱和度克制", "cooler palette, restrained saturation"
    elif color_tendency >= 0.62:
        ct_zh, ct_en = "色彩偏暖、饱和度可略高", "warmer palette, slightly richer saturation"
    else:
        ct_zh, ct_en = "色彩冷暖均衡", "balanced warm-cool palette"

    if density_spacing <= 0.38:
        ds_zh, ds_en = "构图偏满、信息密度较高、留白较少", "dense composition, less negative space"
    elif density_spacing >= 0.62:
        ds_zh, ds_en = "构图疏朗、留白明显、气息舒展", "airy composition with generous negative space"
    else:
        ds_zh, ds_en = "疏密适中", "moderate density and breathing room"

    if era_tone <= 0.38:
        er_zh, er_en = "气质偏古雅与传统笔墨意趣", "classical East Asian mood, ink-painting sensibility"
    elif era_tone >= 0.62:
        er_zh, er_en = "气质偏当代影像与镜头语言", "contemporary cinematic clarity and lens language"
    else:
        er_zh, er_en = "古意与当代感平衡", "blend of classical mood with modern restraint"

    if narrative_symbolism <= 0.38:
        ns_zh, ns_en = "叙事偏直白场景化", "more literal scenic storytelling"
    elif narrative_symbolism >= 0.62:
        ns_zh, ns_en = "叙事偏象征与隐喻层次", "stronger symbolic and metaphorical layers"
    else:
        ns_zh, ns_en = "叙事在直白与象征间折中", "mix of literal scene and subtle symbolism"

    zh = f"{ct_zh}；{ds_zh}；{er_zh}；{ns_zh}。"
    en = f"{ct_en}; {ds_en}; {er_en}; {ns_en}."
    return zh, en


def _size_aspect_hint(size: str) -> str:
    """按输出画幅给构图与留白默认，减少比例失调。"""
    s = (size or "").replace("*", "x").strip().lower()
    parts = re.split(r"[x×]", s, maxsplit=1)
    w, h = 1344, 768
    if len(parts) == 2:
        try:
            w, h = int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            w, h = 1344, 768
    if abs(w - h) < 120:
        return (
            "画幅为方幅：主体宜略偏一侧，另一侧大留白；忌对称呆板摆拍；"
            "纵深可用前景枝石、中景水云、远景淡山分层。"
        )
    if h > w:
        return (
            "画幅为竖幅：纵向气脉为主，可自上而下布置天光—中景—近水/近石；"
            "上下勿平均切块，留一气贯通。"
        )
    return (
        "画幅为横幅：主引导线沿水平延展（岸线、云带、山脊之一），左右气脉连贯；"
        "忌无中心的宽屏空镜与旅游广角。"
    )


def _verse_moon_tide_sea_hint_needed(text: str) -> bool:
    """春江潮水/海上明月等江海月明类句，启用强舞台布置提示。"""
    if not text:
        return False
    t = (text or "").replace(" ", "").strip()
    if any(k in t for k in ("春江潮水", "海上明月", "潮水连海", "连海平", "月共潮生", "明月共潮")):
        return True
    if "潮" in t and "月" in t and ("江" in t or "海" in t):
        return True
    if "海" in t and "月" in t and ("潮" in t or "水" in t):
        return True
    return False


_VM_MOON_TIDE_STAGE_BLOCK = (
    "【江海月明舞台】须显式画出：清晰海平线或潮线与天际关系；明月或月侧高光；"
    "水面一条镜面反射光带自月向画面前缘延展；中近景须有碎浪波纹、潮水进退或浪脊层次，不可平滑死海；"
    "远景可有薄雾山影、帆影或岸线择句而入。"
    "【禁止】原句无人物语义时，禁止用孤零零的巨型人物剪影立于海面正中充当所谓意境；"
    "若有人物须与舟、岸、桥、楼台等物象形成动作或对视关系。"
)

_VM_COMPOSITION_DENSITY_FLOOR = (
    "【信息密度】前景与中景、或中景与远景至少两层须有可辨物象（岸渚、礁石、舟楫、树影、帆缆等，须贴合原句），"
    "禁止仅靠渐变天空+平面海面构成画面；须有可读的浪、纹、岸或船体之一以上层次。"
)


def _image_director_enabled() -> bool:
    """默认开启场景导演二次 GLM；仅当 VERSEMESH_IMAGE_DIRECTOR=0/false/off/no 时关闭。"""
    v = os.environ.get("VERSEMESH_IMAGE_DIRECTOR", "").strip().lower()
    return v not in ("0", "false", "off", "no")


def _director_used_prompt_line(director_cn: str) -> str:
    """used_prompt 中 [DIRECTOR] 段展示文案。"""
    if not _image_director_enabled():
        return "（场景导演：已关闭；环境变量 VERSEMESH_IMAGE_DIRECTOR 为 0/false/off/no）"
    if (director_cn or "").strip():
        return director_cn.strip()
    return "（场景导演：已开启但本轮无附加 JSON 输出）"


def build_image_prompt(
    params,
    input_text,
    abstraction_level,
    tension_level,
    strict_semantics=True,
    color_tendency=0.5,
    density_spacing=0.5,
    era_tone=0.5,
    narrative_symbolism=0.5,
    size="1344x768",
):
    """构造更贴合诗句语义的图像提示词（结构化中文）。"""
    theme = params.get("core_theme", "诗意自然景观")
    color = params.get("color_palette", {}).get("primary_tone", "柔和自然色调")
    composition = params.get("composition", {}).get("horizon_line", "开阔远景构图")
    balance = params.get("composition", {}).get("visual_balance", "画面均衡")
    artist = params.get("artist_reference", "")
    ev = params.get("emotional_vector", {})

    literal_focus = (
        f"请直接表现诗句“{input_text}”描述的场景与意境，主体必须与诗句语义一致，"
        "不要偏离到无关题材。"
    )
    mood_block = (
        f"审美参数：主题={theme}；色彩={color}；构图={composition}；平衡={balance}；"
        f"情绪(宁静={ev.get('tranquility', 50)}, 宏大={ev.get('grandeur', 50)}, 空灵={ev.get('ethereality', 50)})。"
    )
    zh_axes, _en_axes = _style_axes_prompt_fragments(
        color_tendency, density_spacing, era_tone, narrative_symbolism
    )
    control_block = (
        f"控制强度：抽象程度={abstraction_level}（越低越具象），视觉张力={tension_level}。"
        f"调参取向：{zh_axes}"
    )

    # 严格模式下弱化“艺术家参考”，避免跑偏成风格拼贴
    style_ref = "" if strict_semantics else f"可参考风格：{artist}。"

    aspect = _size_aspect_hint(size)
    negative_block = (
        "【禁忌】禁止塑料质感、3D 卡通渲染、游戏宣发海报、影视剧剧照摆拍、乱入现代道具与建筑；"
        "禁止画面内任何文字、水印、角标、二维码；禁止无中心的空镜大平光。"
    )

    narrative_cn = (
        "【叙事与情节】须交代画中正在发生的一件小事或一个转折瞬间（谁、在何处、作何动作或与何物相对）；"
        "避免只有景物陈列而无事件；可与隐喻并存，但观者须能读懂「此刻」。"
    )
    moon_tide = _VM_MOON_TIDE_STAGE_BLOCK if _verse_moon_tide_sea_hint_needed(input_text) else ""
    return (
        "【体裁】中国诗意绘画式图像，绢本/水墨晕染气质，非摄影棚、非商业广告。\n"
        f"【画幅】{aspect}\n"
        f"{_VM_COMPOSITION_DENSITY_FLOOR}\n"
        f"{narrative_cn}\n"
        + (f"{moon_tide}\n" if moon_tide else "")
        + "【语义】"
        + literal_focus
        + "\n"
        + mood_block
        + control_block
        + style_ref
        + negative_block
    )


def build_scene_prompt_en(
    params,
    input_text,
    abstraction_level,
    tension_level,
    strict_semantics=True,
    color_tendency=0.5,
    density_spacing=0.5,
    era_tone=0.5,
    narrative_symbolism=0.5,
    size="1344x768",
):
    """
    英文辅约束：画意、留白、反剧照；避免模型把中文诗句画成画面文字。
    """
    theme = params.get("core_theme", "poetic natural landscape")
    color = params.get("color_palette", {}).get("primary_tone", "natural warm-cool palette")
    composition = params.get("composition", {}).get("horizon_line", "wide horizon composition")
    balance = params.get("composition", {}).get("visual_balance", "balanced layout")
    ev = params.get("emotional_vector", {})

    abstraction_tag = "grounded poetic scene with ink-wash sensibility" if abstraction_level <= 0.45 else "semi-abstract poetic scene with breathing negative space"
    tension_tag = "quiet restrained atmosphere" if tension_level <= 0.55 else "strong yet still painterly atmosphere, not blockbuster lighting"
    semantic_weight = "strictly align with the poem meaning" if strict_semantics else "loosely inspired by poetic mood"
    _zh_axes, en_axes = _style_axes_prompt_fragments(
        color_tendency, density_spacing, era_tone, narrative_symbolism
    )
    aspect_en = _size_aspect_hint(size).replace("。", ". ")
    marine_en = ""
    if _verse_moon_tide_sea_hint_needed(input_text):
        marine_en = (
            "If the verse evokes sea, tide, and moon: show a clear horizon, moon or moon-glow, a bright specular reflection "
            "path on the water, readable wave crests or tidal texture in mid/foreground, and at least one shore/sail distant cue; "
            "do not use a lone giant human silhouette centered on empty sea when the poem has no human subject. "
        )

    return (
        "Chinese poetic PAINTING-like image (not a movie still, not a 3D render, not a commercial poster). "
        f"{abstraction_tag}, {tension_tag}, {semantic_weight}. "
        f"Theme: {theme}. Palette: {color}. Layout: {composition}, {balance}. "
        f"Aspect framing note: {aspect_en} "
        f"Emotion scores: tranquility {ev.get('tranquility', 50)}/100, grandeur {ev.get('grandeur', 50)}/100, "
        f"ethereality {ev.get('ethereality', 50)}/100. "
        f"Slider mood: {en_axes} "
        f"Poem meaning (do not render as text): {input_text}. "
        "Minimum pictorial density: foreground/midground or mid/background must carry at least two readable layers "
        "(shore, rocks, boat, trees, sails—must match the poem), not a flat gradient sky+sea void. "
        f"{marine_en}"
        "Use soft natural light, layered depth, restrained lens, generous negative space where appropriate. "
        "Readable story beat in one frame: who/what, where, doing what, or reacting to what—avoid empty moodboards. "
        "NO text, NO Chinese characters, NO typography, NO logos, NO watermark, NO UI, NO plastic skin, NO neon cyberpunk."
    )


def _extract_json_from_text(raw_text):
    """兼容 markdown/codeblock 的 JSON 解析。"""
    if not raw_text:
        return None
    text = raw_text.strip()
    if not text:
        return None
    block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if block:
        text = block.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


_FLORA_KEYWORDS = (
    "花", "瓣", "蕊", "桃", "李", "梨", "荷", "菊", "兰", "莲", "杏", "棠", "樱", "桂", "蔷薇", "芍", "榴", "梅"
)
_SNOW_KEYWORDS = ("雪", "冰", "霜", "寒", "冬", "霰", "凛冽")


def _text_mentions_flora(text: str) -> bool:
    if not text:
        return False
    return any(k in text for k in _FLORA_KEYWORDS)


def _soul_mentions_flora(soul) -> bool:
    if not soul or not isinstance(soul, dict):
        return False
    parts = [
        str(soul.get("visual_metaphor", "")),
        str(soul.get("literal_trap", "")),
        str(soul.get("rhetoric", "")),
        str(soul.get("symbolism", "")),
    ]
    parts.extend(soul.get("key_imagery") or [])
    parts.extend(soul.get("atmosphere_words") or [])
    blob = " ".join(parts)
    return any(k in blob for k in _FLORA_KEYWORDS)


def _text_mentions_snow_or_cold(text: str) -> bool:
    if not text:
        return False
    return any(k in text for k in _SNOW_KEYWORDS)


def build_poetic_soul_brief(input_text):
    """
    专为古诗/短句做二次语义提纯，补充意象与情绪动态，减少“模板化空镜”。
    """
    system_prompt = """你是中国古典诗词视觉化导演，请把诗句拆解为可用于文生图的“诗魂结构”，尤其要有故事与动作，不能只写氛围。
只输出合法JSON，不要解释，不要markdown。
JSON结构：
{
  "era_style": "可选：唐宋气质/水墨画意/含蓄写实等",
  "core_emotion": "核心情绪，8字以内",
  "emotion_arc": "情绪流动，如 由静到昂扬/由冷到暖",
  "rhetoric": "修辞识别，如 比喻/通感/夸张/对比",
  "visual_metaphor": "修辞转译为画面策略，如 雪似梨花、冷中见春",
  "metaphor_priority": "true/false，是否应优先按隐喻而非字面生成",
  "literal_trap": "常见字面误读点，如把'梨花开'画成真实春季花海",
  "scene_time": "时间与时令，如 早春黎明/深秋黄昏",
  "key_imagery": ["3-6个关键意象，具体可视化名词"],
  "subject_action": "主体动作或状态，须含可见动词，避免静止空镜",
  "narrative_beat": "2-4句中文：画中可见的小情节链（谁/何物在做什么、因何如此、与谁或何物相对）",
  "story_turn": "一句中文：画面的矛盾、转折或扣题瞬间，观者一眼能懂",
  "time_before_after": "一句中文：暗示来处或去处，使单幅有前后时间感",
  "symbolism": "象征含义，1句",
  "camera_language": "镜头建议，如 低机位远景+纵深引导",
  "color_light": "色彩与光线建议",
  "atmosphere_words": ["4-8个氛围词"],
  "must_avoid": ["3-8个需要避免的跑题元素；无人物句须含：禁止孤立巨型人物剪影立于海面正中充意境；禁止纯渐变天空+平面海面无浪纹与岸渚层次"]
}
须保证 narrative_beat、story_turn、time_before_after 含可见动词与空间关系（望远、行舟、倚栏等），并支持前景—中景—远景至少两层与诗句贴合的可辨物象。"""
    user_prompt = f"请解析这句文本的诗魂结构并输出JSON：\n{input_text}"
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        message_text = _get_message_text(response.choices[0].message)
        return _extract_json_from_text(message_text)
    except Exception:
        return None


def build_scene_prompt_poetic(
    params,
    input_text,
    abstraction_level,
    tension_level,
    strict_semantics=True,
    color_tendency=0.5,
    density_spacing=0.5,
    era_tone=0.5,
    narrative_symbolism=0.5,
    size="1344x768",
):
    """
    构造更“有诗魂”的中文提示词，适配万相中文语义理解。
    """
    aspect_block = _size_aspect_hint(size)
    theme = params.get("core_theme", "诗意自然景观")
    color = params.get("color_palette", {}).get("primary_tone", "清冷自然色调")
    composition = params.get("composition", {}).get("horizon_line", "纵深远景构图")
    balance = params.get("composition", {}).get("visual_balance", "均衡有呼吸感")
    ev = params.get("emotional_vector", {})

    abstraction_text = "偏具象写实" if abstraction_level <= 0.35 else ("写实与意象融合" if abstraction_level <= 0.7 else "偏意象表达")
    tension_text = "克制、宁静" if tension_level <= 0.45 else ("有内在张力" if tension_level <= 0.75 else "情绪冲击感明显")
    zh_axes, _en_axes = _style_axes_prompt_fragments(
        color_tendency, density_spacing, era_tone, narrative_symbolism
    )
    strict_text = "必须严格贴合原句语义，不可改题" if strict_semantics else "可在不偏题前提下做适度艺术延展"
    cinematic_strength = (
        "画意镜头：透视与景深克制，少特写少摆拍，留白与空气感明显，忌影视剧剧照、综艺宣发海报式构图与打光。"
        if tension_level > 0.7
        else "画意镜头：以远景与中景为主，气韵连贯、留白推进情绪，忌剧照感与广告级炫光。"
    )

    text_lower = (input_text or "").lower()
    has_human_hint = any(k in input_text for k in ["人", "翁", "君", "我", "你", "他", "她"]) or any(
        k in text_lower for k in ["man", "woman", "person", "people"]
    )
    soul = build_poetic_soul_brief(input_text)
    has_flora = _text_mentions_flora(input_text or "") or _soul_mentions_flora(soul)
    has_snow = _text_mentions_snow_or_cold(input_text or "")

    if abstraction_level <= 0.5:
        if has_flora:
            lens_rule = (
                "镜头优先：花枝与空间呼应，前景可特写与句意相符的花木枝梢，中景延展，远景留白，浅景深，"
                "主体占比随疏密滑块微调，勿堆砌与句外无关的花卉。"
            )
        else:
            lens_rule = (
                "镜头优先：以水岸线、天际线或月光反射带之一为主引导线，中景铺陈句中物象（如山、帆、潮、云），"
                "远景留虚白，浅景深；无花意象则禁止写花、禁止以满枝白花充前景。"
            )
            if density_spacing <= 0.38:
                lens_rule += "构图可略满，仍以句中已有物象为据，不用花补空。"
            elif density_spacing >= 0.62:
                lens_rule += "构图偏疏朗，气脉以长线引导，留白与句意一致。"
    else:
        lens_rule = "镜头优先：中近景诗意主体，保留纵深与留白，不做平铺纪录照。"

    if has_flora:
        motion_detail = (
            "动态细节：可写微风拂瓣、落瓣随波或枝梢轻颤，与光屑、水汽等择其二搭配，勿堆满画框；"
            "无句外强加花阵。"
        )
    elif has_snow:
        motion_detail = (
            "动态细节：可写雪屑轻扬、寒枝微颤或冰面细漪，配以克制空气颗粒与月晕层次；"
            "无春花句不写桃李梨杏等春花。"
        )
    else:
        motion_detail = (
            "动态细节：以水纹粼光、月晕穿行、行云薄霭、飞沫或烟尘微粒中择其二写出微动，"
            "可配与句意相符的枝影轻摆（无花不写花瓣）；空气颗粒与光晕层次保持克制。"
        )
    if has_human_hint:
        motion_detail += "有人物时可加衣袂飘举，须服从诗意，不可喧宾夺主。"
    rhetorical_hint = ""
    anti_literal_hint = ""
    if "忽如一夜" in input_text or "千树万树" in input_text or "梨花" in input_text:
        rhetorical_hint = (
            "修辞转译重点：这句常含比喻与夸张，不是普通写景；"
            "需表现“骤然变化”的时间冲击，以及“雪似梨花/冷中见春”的双重意象。"
        )
        anti_literal_hint = (
            "关键纠偏：'梨花开'在此优先作为雪景比喻，不要渲染成真实春季梨花园；"
            "枝头主体应以雪覆枝条为主，可有极少量花意错觉但不能主导画面。"
        )
    if soul:
        imagery = "、".join(soul.get("key_imagery", []))
        atmos = "、".join(soul.get("atmosphere_words", []))
        avoid = "、".join(soul.get("must_avoid", []))
        subject_action = soul.get("subject_action", "画面需有轻微动态与呼吸感")
        if not has_human_hint:
            subject_action = "禁止人物主体，仅通过风、雪、云、水、树枝等自然元素呈现动态"
        n_beat = (soul.get("narrative_beat") or "").strip()
        s_turn = (soul.get("story_turn") or "").strip()
        t_ba = (soul.get("time_before_after") or "").strip()
        soul_block = (
            f"诗魂拆解：时代气质={soul.get('era_style', '东方诗意画意')}；"
            f"核心情绪={soul.get('core_emotion', '含蓄辽阔')}；"
            f"情绪走向={soul.get('emotion_arc', '由静入深')}；"
            f"修辞识别={soul.get('rhetoric', '比喻与对比')}；"
            f"修辞转译={soul.get('visual_metaphor', '将抽象诗意转为可见光影与动态细节')}；"
            f"隐喻优先={soul.get('metaphor_priority', 'true')}；"
            f"字面陷阱={soul.get('literal_trap', '避免把诗眼直接画成直白物象')}；"
            f"时间场景={soul.get('scene_time', '自然季节场景')}；"
            f"关键意象={imagery if imagery else '按原句提炼'}；"
            f"主体状态={subject_action}；"
            f"情节链={n_beat if n_beat else '按原句提炼可见动作与关系'}；"
            f"画内转折={s_turn if s_turn else '提炼一句诗眼瞬间'}；"
            f"时间暗示={t_ba if t_ba else '略暗示来处或去处'}；"
            f"象征内核={soul.get('symbolism', '保留原诗精神隐喻')}；"
            f"镜头语言={soul.get('camera_language', '远中近层次分明，突出纵深')}；"
            f"光色建议={soul.get('color_light', '自然光影，冷暖克制')}；"
            f"氛围词={atmos if atmos else '空灵、克制、辽阔'}。"
        )
        avoid_block = (
            f"严格避免：{avoid if avoid else '现代城市符号、卡通化、海报排版、文字水印'}；"
            "现代露营帐篷、冲锋衣摆拍、现代道具、现代建筑、塑料与蜡质高光、3D 游戏宣发脸模与肢体。"
        )
    else:
        soul_block = (
            "诗魂拆解失败时按默认策略：强调东方诗性、留白、层次纵深、微动态叙事，"
            "并须安排一句可见的情节或动作转折，避免单调静态空镜与言之无物。"
        )
        avoid_block = (
            "严格避免：现代城市符号、过度赛博元素、海报排版、文字水印、帐篷和现代人物摆拍、"
            "塑料质感与过度立体渲染。"
        )

    human_rule = "若原句未出现人物语义，禁止出现任何人物。" if not has_human_hint else "人物需服从诗意语境，不可喧宾夺主。"
    extra_flora_guard = (
        "补充约束：句中无花木意象时，严禁以满枝白花、梨花、桃林等句外花卉凑景。"
        if strict_semantics and not has_flora
        else ""
    )
    narrative_layer = (
        "【叙事层】单幅内须呈现可读的故事瞬间：明确环境里的主体（人或物）及其处境；"
        "用走向、停驻、对视、回望、拾取、俯仰等可见动作组织因果，避免只有氛围词而无事件。"
        "【画内情节】须让观众感到此刻正在发生什么，可有含蓄留白，不可言不及义、不可纯装饰空镜。"
    )
    moon_tide_poetic = _VM_MOON_TIDE_STAGE_BLOCK if _verse_moon_tide_sea_hint_needed(input_text) else ""

    return (
        f"请根据原句生成高质量图像：{input_text}。"
        f"{strict_text}。"
        f"【画幅与构图】{aspect_block}"
        f"{_VM_COMPOSITION_DENSITY_FLOOR}"
        + (moon_tide_poetic if moon_tide_poetic else "")
        + f"{narrative_layer}"
        f"创作目标：不是普通风景照，而是有诗眼、有留白、有情绪推进的东方诗性画面。"
        f"基础审美参数：主题={theme}；色彩={color}；构图={composition}；平衡={balance}；"
        f"情绪向量(宁静={ev.get('tranquility', 50)},宏大={ev.get('grandeur', 50)},空灵={ev.get('ethereality', 50)})；"
        f"抽象控制={abstraction_text}；张力控制={tension_text}。"
        f"调参取向：{zh_axes}"
        f"艺术化要求：{cinematic_strength}；{lens_rule}"
        f"{motion_detail}"
        f"{extra_flora_guard}"
        f"{rhetorical_hint}"
        f"{anti_literal_hint}"
        f"{soul_block}"
        f"{avoid_block}"
        f"{human_rule}"
        "画面要求：笔墨与空间层次含蓄而分明，主体与留白相生，光影如绢本晕染般自然，禁旅游打卡广角、禁平铺无气大全景，禁 3D 卡通与塑料质感，不出现任何文字或 logo。"
        "若诗句存在比喻，必须优先表达比喻关系与情绪反差，而非字面名词堆砌。"
    )


def _wan_image_director_addon(params, input_text, size, strict_semantics) -> str:
    """
    二次 GLM「场景导演」JSON，拼入 Wan 中文提示；默认开启。
    设 VERSEMESH_IMAGE_DIRECTOR=0 / false / off / no 可关闭（省一次调用）。
    """
    if not _image_director_enabled():
        return ""
    lean = {
        "core_theme": params.get("core_theme"),
        "color_palette": params.get("color_palette"),
        "composition": params.get("composition"),
        "emotional_vector": params.get("emotional_vector"),
    }
    marine = _verse_moon_tide_sea_hint_needed(input_text)
    sys_p = """你是文生图「场景导演」。根据原句与审美 JSON，只输出合法 JSON，不要 markdown，不要解释。
JSON 结构：
{
  "focal_subject": "一两句中文：画面唯一或主次主体",
  "narrative_beat": "2-3句：可见动作链或小情节",
  "story_turn": "一句：矛盾或转折瞬间",
  "spatial_layout": "一两句：前景/中景/远景与留白，须两层以上可辨物象",
  "light_color": "一两句：光与色（绢本晕染气质）",
  "camera": "一两句：机位、景别、纵深；忌剧照特写、忌大头摆拍",
  "tide_horizon_wave_read": "1-2句：海平线或潮线、中近景浪纹/碎波可读层次；非江海潮月句可写「非此类」",
  "moon_reflection_path": "1-2句：月或月侧高光与水面镜面反射光带走向；非此类可写「非此类」",
  "shoreline_foreground_cues": "1-2句：岸渚/礁石/舟楫/帆影等须贴合原句；非此类可写「非此类」",
  "forbidden": ["4-10 条中文禁忌，含塑料/3D/宣发/水印、无人物句忌海面孤立大剪影人等"],
  "en_keywords": ["6-12 个英文关键词，风格辅约束"]
}
若 user 中 marine_moon_class 为 true（春江潮水/海上明月/连海平等江海月明类），tide_horizon_wave_read、moon_reflection_path、shoreline_foreground_cues 必须写满可执行短句，不可敷衍为「非此类」。"""
    user_p = json.dumps(
        {
            "verse": input_text,
            "params": lean,
            "size": size,
            "strict_semantics": strict_semantics,
            "marine_moon_class": marine,
        },
        ensure_ascii=False,
    )
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": sys_p},
                {"role": "user", "content": user_p},
            ],
            temperature=0.35,
            max_tokens=700,
        )
        raw = _get_message_text(response.choices[0].message)
        data = _extract_json_from_text(raw)
        if not data or not isinstance(data, dict):
            return ""
        forb = "；".join(data.get("forbidden") or [])
        enkw = ", ".join(data.get("en_keywords") or [])
        th = (data.get("tide_horizon_wave_read") or "").strip()
        mr = (data.get("moon_reflection_path") or "").strip()
        sh = (data.get("shoreline_foreground_cues") or "").strip()
        marine_line = ""
        if th or mr or sh:
            marine_line = f"潮线与浪读：{th} 月与反射光带：{mr} 岸与近景物象：{sh} "
        return (
            "\n\n【场景导演】"
            f"主体：{data.get('focal_subject', '')} "
            f"情节：{data.get('narrative_beat', '')} "
            f"转折：{data.get('story_turn', '')} "
            f"空间：{data.get('spatial_layout', '')} "
            f"光色：{data.get('light_color', '')} "
            f"镜头：{data.get('camera', '')} "
            f"{marine_line}"
            f"禁忌：{forb} "
            f"英文辅词：{enkw}"
        )
    except Exception:
        return ""


def generate_image_with_wan(
    params,
    input_text,
    abstraction_level,
    tension_level,
    size="1344x768",
    style="natural",
    strict_semantics=True,
    color_tendency=0.5,
    density_spacing=0.5,
    era_tone=0.5,
    narrative_symbolism=0.5,
):
    """根据审美参数调用百炼 wan2.7-image-pro 图像生成接口。"""
    if not params:
        return None, None
    if not bailian_api_key:
        st.error("图像生成失败：未配置 BAILIAN_API_KEY")
        _vm_hint("请在项目根目录 .env 中添加 BAILIAN_API_KEY=你的百炼API Key，然后重启应用。")
        return None, None

    prompt_cn = build_image_prompt(
        params=params,
        input_text=input_text,
        abstraction_level=abstraction_level,
        tension_level=tension_level,
        strict_semantics=strict_semantics,
        color_tendency=color_tendency,
        density_spacing=density_spacing,
        era_tone=era_tone,
        narrative_symbolism=narrative_symbolism,
        size=size,
    )
    prompt = build_scene_prompt_en(
        params=params,
        input_text=input_text,
        abstraction_level=abstraction_level,
        tension_level=tension_level,
        strict_semantics=strict_semantics,
        color_tendency=color_tendency,
        density_spacing=density_spacing,
        era_tone=era_tone,
        narrative_symbolism=narrative_symbolism,
        size=size,
    )
    prompt_poetic = build_scene_prompt_poetic(
        params=params,
        input_text=input_text,
        abstraction_level=abstraction_level,
        tension_level=tension_level,
        strict_semantics=strict_semantics,
        color_tendency=color_tendency,
        density_spacing=density_spacing,
        era_tone=era_tone,
        narrative_symbolism=narrative_symbolism,
        size=size,
    )
    director_cn = _wan_image_director_addon(params, input_text, size, strict_semantics)

    try:
        size_value = size.replace("x", "*")
        style_hint_cn = (
            "【风格层】可略鲜明，须保持绢本设色与空气透视，忌塑料高光、忌 3D 卡通宣发、忌剧照式摆拍与硬边 HDR。"
            if style == "vivid"
            else "【风格层】偏自然晕染与柔和明暗过渡，忌炫光海报、忌过度锐化与数码磨皮感。"
        )
        # Wan 对中文指令更稳定；英文段作辅约束
        prompt_with_style = (
            f"{prompt_poetic}{style_hint_cn}{director_cn}\n\n"
            f"【英文辅约束】{prompt}\n"
            "【安全】NO text, NO watermark, NO logo, NO subtitles."
        )
        payload = {
            "model": image_model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt_with_style}],
                    }
                ]
            },
            "parameters": {
                "size": size_value,
                "n": 1,
                "watermark": False,
            },
        }
        req = urllib_request.Request(
            url=f"{wan_base_url}/services/aigc/multimodal-generation/generation",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {bailian_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8")
        data = json.loads(body) if body else {}

        output = data.get("output") or {}
        choices = output.get("choices") or []
        image_url = None
        if choices and isinstance(choices, list):
            message = choices[0].get("message") or {}
            content = message.get("content") or []
            if content and isinstance(content, list):
                for item in content:
                    if item.get("type") == "image" and item.get("image"):
                        image_url = item.get("image")
                        break

        used_prompt = (
            f"[POETIC-CN]\n{prompt_poetic}\n\n[DIRECTOR]\n{_director_used_prompt_line(director_cn)}\n\n"
            f"[EN-AUX]\n{prompt}\n\n[BASIC-CN]\n{prompt_cn}"
        )
        return image_url, used_prompt
    except urllib_error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        if e.code == 401:
            st.error("图像生成失败：401 身份验证失败（请检查 BAILIAN_API_KEY）")
        else:
            st.error(f"图像生成状态错误：HTTP {e.code}")
        if body:
            _vm_hint(f"接口返回：{body[:300]}")
        return None, (
            f"[POETIC-CN]\n{prompt_poetic}\n\n[DIRECTOR]\n{_director_used_prompt_line(director_cn)}\n\n"
            f"[EN-AUX]\n{prompt}\n\n[BASIC-CN]\n{prompt_cn}"
        )
    except urllib_error.URLError as e:
        st.error(f"图像生成网络错误：{e}")
        return None, (
            f"[POETIC-CN]\n{prompt_poetic}\n\n[DIRECTOR]\n{_director_used_prompt_line(director_cn)}\n\n"
            f"[EN-AUX]\n{prompt}\n\n[BASIC-CN]\n{prompt_cn}"
        )
    except Exception as e:
        st.error(f"图像生成失败：{e}")
        return None, (
            f"[POETIC-CN]\n{prompt_poetic}\n\n[DIRECTOR]\n{_director_used_prompt_line(director_cn)}\n\n"
            f"[EN-AUX]\n{prompt}\n\n[BASIC-CN]\n{prompt_cn}"
        )

_APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _first_existing_file(*candidates):
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


def _data_uri_from_file(path: str) -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    lower = path.lower()
    if lower.endswith(".png"):
        mime = "image/png"
    elif lower.endswith((".jpg", ".jpeg")):
        mime = "image/jpeg"
    elif lower.endswith(".webp"):
        mime = "image/webp"
    elif lower.endswith((".tif", ".tiff")):
        mime = "image/tiff"
    elif lower.endswith(".woff2"):
        mime = "font/woff2"
    elif lower.endswith(".woff"):
        mime = "font/woff"
    elif lower.endswith(".ttf"):
        mime = "font/ttf"
    elif lower.endswith(".otf"):
        mime = "font/otf"
    else:
        mime = "application/octet-stream"
    return f"data:{mime};base64,{b64}"


# 全页背景虚化强度（px）。强弱用此数值近似，不是 CSS blur 百分比；宜 4~6，越小底图越清晰，可调。
BLUR_GLOBAL_PX = 5


def _han_global_bg_path():
    """全页 .stApp::before：图 1（多文件名候选）。"""
    return _first_existing_file(
        os.path.join(_APP_DIR, "static", "han_xizai1.png"),
        os.path.join(_APP_DIR, "static", "han_xizai 1.png"),
        os.path.join(_APP_DIR, "han_xizai1.png"),
        os.path.join(_APP_DIR, "han_xizai 1.png"),
        os.path.join(_APP_DIR, "han_xizai_hero.jpg"),
        os.path.join(_APP_DIR, "static", "han_xizai_hero.jpg"),
    )


def _han_hero_panel_path():
    """仅 Hero 卡内 .vm-hero-painting：图 2。"""
    return _first_existing_file(
        os.path.join(_APP_DIR, "static", "han_xizai2.png"),
        os.path.join(_APP_DIR, "han_xizai2.png"),
        os.path.join(_APP_DIR, "static", "han_xizai_hero.jpg"),
        os.path.join(_APP_DIR, "han_xizai_hero.jpg"),
    )


def _font_format_for_path(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".woff2"):
        return "woff2"
    if lower.endswith(".woff"):
        return "woff"
    if lower.endswith(".ttf"):
        return "truetype"
    if lower.endswith(".otf"):
        return "opentype"
    return "truetype"


def _hero_title_font_path():
    """主标题「诗意晶格」竖排（简体与瘦金书字形集一致，见 _render_hero_html 注释）：首选方正瘦金书繁体…（@font-face 名 VM TitleZh）。"""
    return _first_existing_file(
        os.path.join(_APP_DIR, "static", "fonts", "方正瘦金书繁体.TTF"),
        os.path.join(_APP_DIR, "static", "fonts", "方正字迹-吕建德行楷简体.TTF"),
        os.path.join(_APP_DIR, "static", "fonts", "丛台-肖进生丛台体.TTF"),
        os.path.join(_APP_DIR, "static", "fonts", "方正章草简体.TTF"),
    )


def _jiandu_font_path():
    """侧栏标题、核心价值卡片标题：方正字迹-俊坡简牍繁体。"""
    return _first_existing_file(
        os.path.join(_APP_DIR, "static", "fonts", "方正字迹-俊坡简牍繁体.TTF"),
    )


def _sidebar_texture_path():
    """侧栏品牌区底纹 Texture.png（多路径候选）。"""
    return _first_existing_file(
        os.path.join(_APP_DIR, "static", "fonts", "Texture.png"),
        os.path.join(_APP_DIR, "static", "Texture.png"),
    )


def _welcome_sn_path():
    """欢迎区 .vm-welcome-panel 衬底 sn.png（多路径候选）；侧栏不使用。"""
    return _first_existing_file(
        os.path.join(_APP_DIR, "static", "sn.png"),
        os.path.join(_APP_DIR, "static", "fonts", "sn.png"),
    )


def _primary_btn_texture_path():
    """主按钮（primary）底图：优先 Texture42，回退千里江山水纹。"""
    return _first_existing_file(
        os.path.join(_APP_DIR, "static", "fonts", "Texture42.png"),
        os.path.join(_APP_DIR, "static", "Texture42.png"),
        os.path.join(_APP_DIR, "static", "fonts", "千里江山图水纹2.jpg"),
        os.path.join(_APP_DIR, "static", "千里江山图水纹2.jpg"),
    )


def _compile_btn_texture_path():
    """侧栏「执行编译」primary 底图：Texture25（fonts 优先，回退 static）。"""
    return _first_existing_file(
        os.path.join(_APP_DIR, "static", "fonts", "Texture25.png"),
        os.path.join(_APP_DIR, "static", "Texture25.png"),
    )


def _inject_primary_button_css():
    p = _primary_btn_texture_path()
    if not p:
        return
    u = _data_uri_from_file(p)
    st.markdown(
        f"""<style>
section[data-testid="stMain"] .stButton > button[kind="primary"] {{
  background-image: linear-gradient(180deg, rgba(12, 28, 38, 0.42), rgba(6, 18, 28, 0.55)), url('{u}') !important;
  background-size: cover, cover !important;
  background-position: center, center !important;
  color: #fffaf0 !important;
  font-weight: 600 !important;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.78), 0 0 18px rgba(0, 0, 0, 0.4) !important;
  border: 1px solid rgba(52, 78, 88, 0.95) !important;
  box-shadow: inset 0 1px 0 rgba(255, 252, 245, 0.28), 0 5px 0 rgba(18, 38, 48, 0.58), 0 8px 22px rgba(24, 48, 58, 0.22) !important;
}}
section[data-testid="stMain"] .stButton > button[kind="primary"]:hover {{
  filter: brightness(1.08) saturate(1.05) !important;
}}
section[data-testid="stMain"] .stButton > button[kind="primary"]:disabled {{
  filter: grayscale(0.4) brightness(0.9) !important;
  opacity: 0.88 !important;
}}
</style>""",
        unsafe_allow_html=True,
    )


def _inject_sidebar_compile_button_css():
    """仅侧栏 primary（执行编译）使用 Texture25，与主区 Texture42 分流。"""
    p = _compile_btn_texture_path()
    if not p:
        return
    u = _data_uri_from_file(p)
    st.markdown(
        f"""<style>
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
  background-image: linear-gradient(180deg, rgba(14, 30, 40, 0.48), rgba(6, 18, 28, 0.58)), url('{u}') !important;
  background-size: cover, cover !important;
  background-position: center, center !important;
  color: #fffaf0 !important;
  font-weight: 600 !important;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8), 0 0 18px rgba(0, 0, 0, 0.42) !important;
  border: 1px solid rgba(50, 76, 86, 0.95) !important;
  box-shadow: inset 0 1px 0 rgba(255, 252, 245, 0.26), 0 5px 0 rgba(16, 36, 46, 0.56), 0 8px 22px rgba(22, 44, 54, 0.22) !important;
}}
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {{
  filter: brightness(1.08) saturate(1.05) !important;
}}
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:disabled {{
  filter: grayscale(0.4) brightness(0.9) !important;
  opacity: 0.88 !important;
}}
</style>""",
        unsafe_allow_html=True,
    )


def _debug_button_texture_captions() -> None:
    if os.environ.get("VERSEMESH_DEBUG", "").strip().lower() not in ("1", "true", "yes"):
        return
    c = _compile_btn_texture_path()
    m = _primary_btn_texture_path()
    st.caption(f"侧栏「执行编译」底图：{c or '（无）'} | 主区 primary 底图：{m or '（无）'}")


def _inject_sidebar_scroll_tooltip_css():
    """侧栏内容区可滚动；浅色 Tooltip，修复 help 黑底深字。"""
    st.markdown(
        """
<style>
  section[data-testid="stSidebar"] {
    overflow: hidden !important;
    align-items: stretch !important;
    display: flex !important;
    flex-direction: column !important;
    max-height: 100vh !important;
  }
  section[data-testid="stSidebar"] > div {
    min-height: 0 !important;
    flex: 1 1 auto !important;
    display: flex !important;
    flex-direction: column !important;
    overflow: hidden !important;
    max-height: 100vh !important;
  }
  section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    min-height: 0 !important;
    flex: 1 1 auto !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    overscroll-behavior: contain !important;
    max-height: calc(100vh - 0.5rem) !important;
    padding-bottom: 0.75rem !important;
  }
  div[data-testid="stTooltip"],
  div[data-testid="stTooltip"] *,
  [data-testid="stTooltip"] {
    color-scheme: light !important;
  }
  div[data-testid="stTooltip"] {
    background-color: #faf6ec !important;
    background-image: linear-gradient(165deg, #fffdf8 0%, #f4ead8 100%) !important;
    color: #1a1612 !important;
    border: 1px solid rgba(196, 181, 154, 0.95) !important;
    border-radius: 10px !important;
    box-shadow: 0 6px 28px rgba(40, 32, 20, 0.18), inset 0 1px 0 rgba(255, 252, 245, 0.65) !important;
    padding: 0.65rem 0.85rem !important;
    font-size: 0.88rem !important;
    line-height: 1.55 !important;
    max-width: min(420px, 92vw) !important;
  }
  div[data-testid="stTooltip"] p,
  div[data-testid="stTooltip"] span,
  div[data-testid="stTooltip"] div,
  div[data-testid="stTooltip"] label {
    color: #1a1612 !important;
    opacity: 1 !important;
  }
  [role="tooltip"] {
    background-color: #faf6ec !important;
    color: #1a1612 !important;
    border: 1px solid rgba(196, 181, 154, 0.9) !important;
    box-shadow: 0 6px 24px rgba(40, 32, 20, 0.16) !important;
    padding: 0.55rem 0.75rem !important;
    font-size: 0.86rem !important;
    line-height: 1.5 !important;
  }
  [role="tooltip"] * {
    color: #1a1612 !important;
  }
  div[data-testid="stExpander"] details,
  div[data-testid="stExpander"] details[open] {
    background: rgba(255, 252, 245, 0.97) !important;
    color: #1a1612 !important;
    border: none !important;
  }
  div[data-testid="stExpander"] summary,
  div[data-testid="stExpander"] summary:hover,
  div[data-testid="stExpander"] summary:focus,
  div[data-testid="stExpander"] summary:focus-visible {
    background: rgba(255, 252, 245, 0.94) !important;
    color: #1a1612 !important;
  }
  div[data-testid="stExpander"] .streamlit-expanderContent,
  div[data-testid="stExpander"] [data-testid="stVerticalBlock"] {
    background: transparent !important;
    color: #1a1612 !important;
  }
  div[data-testid="stExpander"] p,
  div[data-testid="stExpander"] span,
  div[data-testid="stExpander"] label,
  div[data-testid="stExpander"] small {
    color: #1a1612 !important;
  }
  [data-baseweb="popover"],
  [data-baseweb="popover"] > div {
    background-color: #faf6ec !important;
    background-image: linear-gradient(165deg, #fffdf8 0%, #f4ead8 100%) !important;
    color: #1a1612 !important;
    border: 1px solid rgba(196, 181, 154, 0.9) !important;
    box-shadow: 0 8px 28px rgba(40, 32, 20, 0.14) !important;
  }
  [data-baseweb="popover"] * {
    color: #1a1612 !important;
  }
  a.vm-open-image-link {
    display: inline-block;
    margin-top: 0.5rem;
    padding: 0.45rem 0.85rem;
    border-radius: 6px;
    border: 1px solid rgba(196, 181, 154, 0.85);
    background: linear-gradient(180deg, #faf6ec 0%, #ebe3d4 100%);
    color: #1a1612 !important;
    font-weight: 600;
    text-decoration: none !important;
  }
  a.vm-open-image-link:hover {
    filter: brightness(1.03);
  }
</style>
""",
        unsafe_allow_html=True,
    )


def _sidebar_deco_bitmap_path():
    """侧栏品牌装饰：PSD 浏览器不可用，仅加载已导出的 png/jpg。"""
    return _first_existing_file(
        os.path.join(_APP_DIR, "static", "fonts", "JPG分段 (9).png"),
        os.path.join(_APP_DIR, "static", "fonts", "JPG分段 (9).jpg"),
        os.path.join(_APP_DIR, "static", "fonts", "JPG分段 (9).jpeg"),
    )


def _welcome_panel_bg_path():
    """欢迎区主列背景：优先 PNG/WebP，其次 TIF（部分浏览器可能不显示）。"""
    return _first_existing_file(
        os.path.join(_APP_DIR, "static", "fonts", "TIF分段 (11).png"),
        os.path.join(_APP_DIR, "static", "fonts", "TIF分段 (11).webp"),
        os.path.join(_APP_DIR, "static", "fonts", "TIF分段 (11).tiff"),
        os.path.join(_APP_DIR, "static", "fonts", "TIF分段 (11).tif"),
    )


def _inject_texture_panel_css():
    """侧栏整栏 Texture、欢迎区 sn（优先）或 TIF/PNG 回退、品牌装饰；base64。后注入覆盖页首 style 与 _inject_hero_assets_css 中的侧栏底。"""
    bits = []
    tex = _sidebar_texture_path()

    if tex:
        u = _data_uri_from_file(tex)
        bits.append(
            f"""
section[data-testid="stSidebar"] {{
  background-image: linear-gradient(
    165deg,
    rgba(255, 252, 245, 0.52) 0%,
    rgba(248, 240, 224, 0.34) 100%
  ), url('{u}') !important;
  background-size: cover, cover !important;
  background-position: center, center !important;
  background-repeat: no-repeat, no-repeat !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}}
"""
        )
    else:
        bits.append(
            """
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, rgba(252, 248, 238, 0.96) 0%, rgba(235, 224, 204, 0.92) 100%) !important;
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}
"""
        )

    bits.append(
        """
section[data-testid="stSidebar"] .vm-sidebar-brand {
  position: relative;
  background: transparent !important;
  border-radius: 8px;
  padding: 0.82rem 1rem 1.05rem 1rem;
  margin-bottom: 0.4rem;
  border: 1px solid rgba(196, 181, 154, 0.55);
  box-shadow: inset 0 1px 0 rgba(255, 252, 245, 0.35);
  overflow: hidden;
}
section[data-testid="stSidebar"] .vm-sidebar-brand .vm-sidebar-brand-title {
  position: relative;
  z-index: 2;
}
section[data-testid="stSidebar"] .vm-sidebar-input-panel:empty {
  display: none !important;
  height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
}
"""
    )

    deco = _sidebar_deco_bitmap_path()
    if deco:
        d = _data_uri_from_file(deco)
        bits.append(
            f"""
section[data-testid="stSidebar"] .vm-sidebar-brand::after {{
  content: "";
  position: absolute;
  inset: 0;
  background-image: url('{d}');
  background-size: cover;
  background-position: center bottom;
  opacity: 0.2;
  pointer-events: none;
  z-index: 0;
}}
"""
        )
    welcome_sn = _welcome_sn_path()
    if welcome_sn:
        su = _data_uri_from_file(welcome_sn)
        bits.append(
            f"""
.vm-welcome-panel {{
  position: relative;
  background-image: linear-gradient(
    165deg,
    rgba(255, 252, 245, 0.5) 0%,
    rgba(255, 252, 245, 0.62) 100%
  ), url('{su}');
  background-size: auto, cover;
  background-position: center, center;
  border-radius: 10px;
  padding: 1rem 1.15rem 1.2rem 1.15rem;
  border: 1px solid rgba(196, 181, 154, 0.5);
  box-shadow: inset 0 0 0 1px rgba(255, 252, 245, 0.35);
}}
.vm-welcome-panel h3,
.vm-welcome-panel p,
.vm-welcome-panel li {{
  text-shadow: 0 0 8px rgba(255, 252, 245, 0.95), 0 1px 2px rgba(40, 32, 20, 0.12);
}}
"""
        )
    else:
        wp = _welcome_panel_bg_path()
        if wp:
            w = _data_uri_from_file(wp)
            bits.append(
                f"""
.vm-welcome-panel {{
  position: relative;
  background-image: url('{w}');
  background-size: cover;
  background-position: center center;
  border-radius: 10px;
  padding: 1rem 1.15rem 1.2rem 1.15rem;
  border: 1px solid rgba(196, 181, 154, 0.5);
  box-shadow: inset 0 0 0 1px rgba(255, 252, 245, 0.35);
}}
.vm-welcome-panel h3,
.vm-welcome-panel p,
.vm-welcome-panel li {{
  text-shadow: 0 0 8px rgba(255, 252, 245, 0.95), 0 1px 2px rgba(40, 32, 20, 0.12);
}}
"""
            )
    if bits:
        st.markdown(f"<style>{''.join(bits)}</style>", unsafe_allow_html=True)


def _inject_hero_assets_css():
    """VM TitleZh（瘦金书优先）/ VM JianDu、全页图1虚化、Hero 图2、主区宣纸实底；base64。方正字库商用请自行确认授权。"""
    chunks = []
    title_font = _hero_title_font_path()
    if title_font:
        fmt = _font_format_for_path(title_font)
        uri = _data_uri_from_file(title_font)
        chunks.append(
            f"""
@font-face {{
  font-family: 'VM TitleZh';
  src: url('{uri}') format('{fmt}');
  font-weight: normal;
  font-style: normal;
  font-display: swap;
}}
"""
        )
    jd = _jiandu_font_path()
    if jd:
        fmt_j = _font_format_for_path(jd)
        uri_j = _data_uri_from_file(jd)
        chunks.append(
            f"""
@font-face {{
  font-family: 'VM JianDu';
  src: url('{uri_j}') format('{fmt_j}');
  font-weight: normal;
  font-style: normal;
  font-display: swap;
}}
"""
        )
        chunks.append(
            """
section[data-testid="stSidebar"] h1 {
  font-family: "VM JianDu", "Ma Shan Zheng", "Noto Serif SC", "SimSun", serif !important;
  letter-spacing: 0.06em !important;
}
.vm-sidebar-brand .vm-sidebar-brand-title {
  font-family: "VM JianDu", "Ma Shan Zheng", "Noto Serif SC", "SimSun", serif !important;
  letter-spacing: 0.04em !important;
}
.vm-scroll-card h3 {
  font-family: "VM JianDu", "Ma Shan Zheng", "Noto Serif SC", serif !important;
  letter-spacing: 0.12em !important;
}
"""
        )

    han_g = _han_global_bg_path()
    if han_g:
        uri_g = _data_uri_from_file(han_g)
        chunks.append(
            f"""
.stApp {{
  background-color: transparent !important;
  background-image: none !important;
}}
.stApp::before {{
  content: "";
  position: fixed;
  inset: 0;
  z-index: 0;
  background-image: url('{uri_g}');
  background-size: cover;
  background-position: center center;
  background-repeat: no-repeat;
  filter: blur({BLUR_GLOBAL_PX}px);
  transform: scale(1.07);
  pointer-events: none;
}}
.stApp::after {{
  content: "";
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: linear-gradient(
    165deg,
    rgba(252, 246, 236, 0.92) 0%,
    rgba(244, 234, 216, 0.82) 45%,
    rgba(200, 188, 168, 0.05) 100%
  );
}}
[data-testid="stAppViewContainer"],
section[data-testid="stSidebar"],
header[data-testid="stHeader"] {{
  position: relative;
  z-index: 1;
}}
section[data-testid="stSidebar"] {{
  min-height: auto !important;
  height: auto !important;
  align-self: flex-start !important;
}}
section[data-testid="stSidebar"] > div {{
  min-height: 0 !important;
  height: auto !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
  min-height: 0 !important;
}}
[data-testid="stAppViewContainer"] {{
  min-height: 100vh !important;
}}
.block-container {{
  background-color: #f2e8d8 !important;
  background-image:
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 22px,
      rgba(60, 48, 32, 0.045) 22px,
      rgba(60, 48, 32, 0.045) 23px
    ),
    linear-gradient(165deg, #faf6ec 0%, #f0e4d0 48%, #e8dcc4 100%) !important;
  border-radius: 10px;
  padding-left: 1rem !important;
  padding-right: 1rem !important;
  min-height: calc(100vh - 5.5rem) !important;
  box-shadow: inset 0 1px 0 rgba(255, 252, 245, 0.55), 0 0 0 1px rgba(196, 181, 154, 0.4), 0 4px 20px rgba(40, 32, 20, 0.06);
}}
"""
        )

    han_h = _han_hero_panel_path()
    if han_h:
        uri_h = _data_uri_from_file(han_h)
        chunks.append(
            f"""
/* Hero 图 2：cover 铺满卡内画幅，与 veil 渐变叠化；contain 会留边故不用 */
.vm-hero-painting {{
  background-image: url('{uri_h}') !important;
  background-size: cover !important;
  background-position: center center !important;
  background-repeat: no-repeat !important;
  background-color: transparent !important;
}}
"""
        )
    else:
        chunks.append(
            """
.vm-hero-painting {
  background-image: linear-gradient(165deg, #e8dcc8 0%, #d4c4a8 45%, #c4b59a 100%) !important;
  background-color: transparent !important;
}
"""
        )

    if chunks:
        st.markdown(f"<style>{''.join(chunks)}</style>", unsafe_allow_html=True)


def _render_hero_html(compact: bool) -> str:
    """Hero HTML：每行以「<」开头，行首禁止≥4 空格，避免 Streamlit Markdown 缩进代码块。
    竖排四字用简体「诗意晶格」：繁体「詩」U+8A69 常不在方正瘦金书繁体 TTF 内，会回退为黑体状首字。"""
    cls = "vm-hero" + (" vm-hero--compact" if compact else "")
    today = datetime.now().strftime("%Y/%m/%d")
    chars = "".join(f'<span class="vm-hero-seal-char">{c}</span>' for c in "诗意晶格")
    return (
        f'<div class="{cls}" dir="ltr" lang="zh-Hans">\n'
        f'<h1 class="vm-sr-only">VerseMesh 诗意晶格</h1>\n'
        f'<div class="vm-hero-card">\n'
        f'<div class="vm-hero-topbar"><span>VERSE MESH</span><span>{today}</span><span>AESTHETIC MESH</span></div>\n'
        f'<div class="vm-hero-body">\n'
        f'<div class="vm-hero-paper" aria-hidden="true"></div>\n'
        f'<div class="vm-hero-painting" role="img" aria-label="韩熙载夜宴图"></div>\n'
        f'<div class="vm-hero-veil" aria-hidden="true"></div>\n'
        f'<div class="vm-hero-overlay">\n'
        f'<div class="vm-hero-editorial">\n'
        f'<div class="vm-hero-ancient-stack">\n'
        f'<span class="vm-hero-ancient">ANCIENT</span>\n'
        f'<p class="vm-hero-bracket">「将文字意境编译为可调参数与绘图指令」</p>\n'
        f"</div>\n"
        f'<p class="vm-hero-tag">AI 审美参数编译器 · 以字为境，化意为象</p>\n'
        f"</div>\n"
        f'<div class="vm-hero-stage">\n'
        f'<div class="vm-hero-seal-title" title="诗意晶格">{chars}</div>\n'
        f"</div>\n</div>\n</div>\n</div>\n</div>\n"
    )


# ==================== 页面配置 ====================
st.set_page_config(
    page_title="VerseMesh · 诗意晶格",
    page_icon="📜",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 古风界面：宣纸底、墨色字、朱砂点缀（Google 字体可离线降级为系统宋体/楷体）
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Ma+Shan+Zheng&family=Noto+Serif+SC:wght@400;600;700&display=swap');

    :root {
        --vm-ink: #1a1612;
        --vm-ink-body: #2a2218;
        --vm-ink-soft: #3d3428;
        --vm-ink-muted: #5c4f42;
        --vm-ink-faint: #7a6b5a;
        --vm-paper: #f4ead8;
        --vm-paper-deep: #e8dcc4;
        --vm-cinnabar: #b03a2e;
        --vm-cinnabar-hover: #c94a3d;
        --vm-gold: #b8860b;
        --vm-gold-dim: rgba(184, 134, 11, 0.35);
        --vm-border: #c4b59a;
        --vm-bamboo: #3d5c4a;
        --vm-shadow: rgba(40, 32, 20, 0.12);
    }

    .stApp,
    section[data-testid="stSidebar"],
    .stMarkdown,
    .stCaption,
    .stButton > button,
    h1:not(.vm-sidebar-brand-title), h2, h3, h4 {
        font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "SimSun", serif !important;
    }
    .stCodeBlock pre, .stCodeBlock code, [data-testid="stCodeBlock"] code {
        font-family: ui-monospace, "Cascadia Mono", Consolas, monospace !important;
    }

    .stApp {
        max-width: 1240px;
        margin: 0 auto;
        background-color: var(--vm-paper);
        background-image:
            radial-gradient(ellipse 900px 420px at 12% -8%, rgba(176, 58, 46, 0.06), transparent 55%),
            radial-gradient(ellipse 700px 380px at 88% 8%, rgba(184, 134, 11, 0.08), transparent 50%),
            repeating-linear-gradient(
                0deg,
                transparent,
                transparent 23px,
                rgba(60, 48, 32, 0.04) 23px,
                rgba(60, 48, 32, 0.04) 24px
            ),
            linear-gradient(165deg, #faf3e6 0%, var(--vm-paper) 42%, #efe4d2 100%);
        color: var(--vm-ink-body);
    }

    header[data-testid="stHeader"] {
        background: transparent;
    }

    .block-container {
        padding-top: 0.65rem;
        padding-bottom: 1.1rem;
        max-width: 1180px;
        min-height: calc(100vh - 5.5rem) !important;
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8f1e4 0%, #ebe0cc 100%) !important;
        border-right: 1px solid var(--vm-border) !important;
        box-shadow: 4px 0 18px var(--vm-shadow);
        align-items: flex-start !important;
    }
    section[data-testid="stSidebar"] > div {
        height: auto !important;
        min-height: 0 !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        min-height: 0 !important;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: var(--vm-ink) !important;
        font-weight: 600;
    }
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] label {
        color: var(--vm-ink-soft) !important;
    }
    section[data-testid="stSidebar"] .vm-sidebar-input-panel .stCaption,
    section[data-testid="stSidebar"] .vm-sidebar-input-panel label {
        color: rgba(255, 252, 245, 0.94) !important;
        text-shadow: 0 1px 3px rgba(0, 0, 0, 0.55), 0 0 12px rgba(26, 22, 18, 0.4) !important;
    }
    section[data-testid="stSidebar"] .stCaption {
        color: rgba(252, 248, 238, 0.92) !important;
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.42) !important;
    }

    h1:not(.vm-sr-only):not(.vm-sidebar-brand-title) {
        font-family: "Ma Shan Zheng", "Noto Serif SC", "KaiTi", "STKaiti", serif !important;
        font-weight: 400;
        font-size: clamp(2.1rem, 4vw, 2.85rem);
        color: var(--vm-ink) !important;
        letter-spacing: 0.12em;
        border-bottom: 2px double var(--vm-gold-dim);
        padding-bottom: 0.55rem;
        text-shadow: 0 1px 0 rgba(255, 255, 255, 0.6);
    }
    .vm-sidebar-brand .vm-sidebar-brand-title {
        margin: 0 !important;
        padding: 0 !important;
        border: none !important;
        font-size: clamp(2rem, 4.4vw, 2.75rem) !important;
        line-height: 1.2 !important;
        text-shadow: 0 1px 0 rgba(255, 252, 245, 0.75);
    }
    h1.vm-sr-only {
        border: none !important;
        padding: 0 !important;
        font-size: 1px !important;
        letter-spacing: 0 !important;
        text-shadow: none !important;
        line-height: 0 !important;
    }
    h2, h3 {
        color: var(--vm-ink) !important;
        font-weight: 600;
        letter-spacing: 0.04em;
    }
    p, li, label, .stMarkdown,
    div[data-testid="stMetricValue"], div[data-testid="stMetricLabel"] {
        color: var(--vm-ink-body) !important;
    }
    .stCaption {
        color: var(--vm-ink-muted) !important;
    }
    div[data-testid="stMetricDelta"] { color: var(--vm-bamboo) !important; }

    hr {
        border: none;
        border-top: 1px solid var(--vm-border);
        opacity: 0.85;
    }

    .vm-hint {
        margin: 0.65rem 0;
        padding: 0;
        border-radius: 8px;
        border: 1px solid rgba(196, 181, 154, 0.65);
        background: linear-gradient(165deg, rgba(252, 248, 238, 0.96) 0%, rgba(236, 226, 208, 0.92) 100%);
        box-shadow: 0 2px 12px rgba(40, 32, 20, 0.07);
    }
    .vm-hint-inner {
        padding: 0.65rem 0.9rem;
        color: var(--vm-ink-body) !important;
        font-size: 0.92rem;
        line-height: 1.55;
    }

    .vm-seal-wait {
        display: inline-block;
        margin: 0.15rem 0 0.45rem 0;
        padding: 0.32rem 0.75rem;
        font-size: 0.82rem;
        letter-spacing: 0.22em;
        color: var(--vm-ink-muted) !important;
        border: 1px double var(--vm-border);
        border-radius: 4px;
        background: linear-gradient(165deg, rgba(252, 248, 238, 0.92), rgba(238, 228, 210, 0.88));
        box-shadow: inset 0 1px 0 rgba(255, 252, 245, 0.55);
        animation: vm-seal-wait-pulse 2.2s ease-in-out infinite;
    }
    @keyframes vm-seal-wait-pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.78; }
    }
    @media (prefers-reduced-motion: reduce) {
        .vm-seal-wait {
            animation: none !important;
        }
    }

    .vm-wait-curtain {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin: 0.35rem 0 0.65rem 0;
        padding: 0.5rem 0.85rem;
        max-width: 36rem;
        border: 1px solid rgba(196, 181, 154, 0.65);
        border-radius: 8px;
        background: linear-gradient(165deg, rgba(252, 248, 238, 0.97), rgba(236, 226, 208, 0.94));
        box-shadow: 0 2px 14px rgba(40, 32, 20, 0.08), inset 0 1px 0 rgba(255, 252, 245, 0.55);
    }
    .vm-wait-seal {
        display: inline-flex;
        width: 2.1rem;
        height: 2.1rem;
        flex: 0 0 auto;
        align-items: center;
        justify-content: center;
        font-family: "Noto Serif SC", "SimSun", serif !important;
        font-size: 0.95rem;
        color: var(--vm-ink) !important;
        border: 2px double rgba(138, 122, 98, 0.85);
        border-radius: 4px;
        background: rgba(255, 252, 245, 0.75);
        animation: vm-wait-spin 3.2s linear infinite;
    }
    @keyframes vm-wait-spin {
        to { transform: rotate(360deg); }
    }
    .vm-wait-copy {
        display: flex;
        flex-direction: column;
        gap: 0.15rem;
        min-width: 0;
    }
    .vm-wait-title {
        font-size: 0.78rem;
        letter-spacing: 0.28em;
        color: var(--vm-ink-muted) !important;
    }
    .vm-wait-tip {
        font-size: 0.88rem;
        color: var(--vm-ink-body) !important;
        letter-spacing: 0.06em;
        line-height: 1.45;
    }
    .vm-wait-curtain--compile {
        border-color: rgba(72, 108, 92, 0.55) !important;
        background: linear-gradient(165deg, rgba(244, 252, 248, 0.98), rgba(218, 234, 224, 0.93)) !important;
        box-shadow: 0 2px 14px rgba(42, 72, 58, 0.1), inset 0 1px 0 rgba(255, 252, 245, 0.55) !important;
    }
    .vm-wait-curtain--compile .vm-wait-seal {
        border-color: rgba(61, 92, 74, 0.55) !important;
        color: #2a4a38 !important;
        background: rgba(255, 252, 245, 0.82) !important;
    }
    .vm-wait-curtain--image {
        border-color: rgba(176, 138, 110, 0.55) !important;
        background: linear-gradient(165deg, rgba(255, 248, 240, 0.98), rgba(238, 218, 198, 0.93)) !important;
        box-shadow: 0 2px 14px rgba(120, 72, 48, 0.08), inset 0 1px 0 rgba(255, 252, 245, 0.55) !important;
    }
    .vm-wait-curtain--image .vm-wait-seal {
        border-color: rgba(176, 120, 88, 0.55) !important;
        color: #5c3828 !important;
        background: rgba(255, 250, 245, 0.85) !important;
    }
    @media (prefers-reduced-motion: reduce) {
        .vm-wait-seal {
            animation: none !important;
        }
    }

    .vm-repro-bar {
        font-size: 0.78rem;
        color: var(--vm-ink-muted) !important;
        letter-spacing: 0.04em;
        line-height: 1.5;
        margin: 0.35rem 0 0.5rem 0;
        padding: 0.4rem 0.65rem;
        border-left: 3px solid rgba(184, 134, 11, 0.45);
        background: rgba(255, 252, 245, 0.55);
        border-radius: 0 6px 6px 0;
    }
    .vm-hint-inner strong {
        color: var(--vm-ink) !important;
        font-weight: 600;
    }

    .vm-footer-sig {
        text-align: center;
        font-style: italic;
        color: var(--vm-ink-soft) !important;
        opacity: 0.9;
        margin: 0.4rem 0 0.2rem 0;
        font-size: 0.9rem;
        letter-spacing: 0.14em;
    }

    .stTextArea textarea,
    .stTextInput input {
        background: rgba(255, 252, 245, 0.92) !important;
        color: var(--vm-ink) !important;
        border: 1px solid var(--vm-border) !important;
        border-radius: 6px !important;
        box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.04);
    }
    .stTextArea textarea::placeholder {
        color: rgba(45, 40, 32, 0.58) !important;
        opacity: 1 !important;
    }
    .stTextArea textarea::-webkit-input-placeholder {
        color: rgba(45, 40, 32, 0.58) !important;
        opacity: 1 !important;
    }

    div[data-baseweb="select"] > div {
        background-color: rgba(255, 252, 245, 0.95) !important;
        border-color: var(--vm-border) !important;
        color: var(--vm-ink) !important;
    }

    .stSlider [data-baseweb="slider"] [data-testid="stTickBarMin"],
    .stSlider [data-baseweb="slider"] [data-testid="stTickBarMax"] {
        color: var(--vm-ink-soft) !important;
    }
    .stSlider [data-baseweb="slider"] [role="slider"] {
        background-color: var(--vm-cinnabar) !important;
        border: 2px solid #fff8e8 !important;
    }
    .stSlider [data-baseweb="slider"] [data-testid="stSliderThumbValue"] {
        color: var(--vm-ink) !important;
    }

    .stButton > button {
        font-family: "Noto Serif SC", "SimSun", serif !important;
        background: linear-gradient(180deg, #c94a3d 0%, var(--vm-cinnabar) 100%) !important;
        color: #fffaf2 !important;
        border: 1px solid #8f2f26 !important;
        border-radius: 6px !important;
        padding: 0.55rem 1.1rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.08em;
        box-shadow: 0 4px 0 #7a261f, 0 8px 16px rgba(120, 40, 30, 0.2);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 5px 0 #7a261f, 0 10px 20px rgba(120, 40, 30, 0.22);
        background: linear-gradient(180deg, #d65548 0%, var(--vm-cinnabar-hover) 100%) !important;
    }
    .stButton > button[kind="secondary"] {
        background: linear-gradient(180deg, #faf6ec 0%, #ebe3d4 100%) !important;
        color: var(--vm-ink) !important;
        border: 1px solid var(--vm-border) !important;
        box-shadow: 0 3px 0 #c9bb9e, 0 6px 12px var(--vm-shadow);
    }
    .stButton > button[kind="secondary"]:hover {
        background: #fffdf6 !important;
        box-shadow: 0 4px 0 #c9bb9e, 0 8px 14px var(--vm-shadow);
    }

    div[data-testid="stExpander"] {
        border: 1px solid var(--vm-border) !important;
        border-radius: 8px !important;
        background: rgba(255, 252, 245, 0.55) !important;
        overflow: hidden;
    }
    div[data-testid="stExpander"] summary {
        color: var(--vm-ink) !important;
        font-weight: 600;
    }

    div[data-testid="stAlert"] {
        border-radius: 8px !important;
        border: 1px solid var(--vm-border) !important;
    }

    .param-card {
        background: linear-gradient(180deg, rgba(255, 252, 245, 0.95), rgba(245, 236, 220, 0.92));
        border-radius: 10px;
        padding: 18px 20px;
        margin: 10px 0;
        box-shadow: 0 6px 20px var(--vm-shadow), inset 0 1px 0 rgba(255, 255, 255, 0.7);
        border: 1px solid var(--vm-border);
        outline: 3px double rgba(184, 134, 11, 0.22);
        outline-offset: 1px;
    }
    .param-card h2, .param-card h3, .param-card p {
        color: var(--vm-ink) !important;
    }

    .success-box {
        background: linear-gradient(135deg, rgba(61, 92, 74, 0.12), rgba(61, 92, 74, 0.06));
        border: 1px solid rgba(61, 92, 74, 0.35);
        border-radius: 8px;
        padding: 14px 16px;
        margin: 14px 0;
        color: var(--vm-ink-soft) !important;
    }

    .image-result-panel {
        background: linear-gradient(180deg, #f9f4ea 0%, #ebe0cf 100%);
        border: 8px solid #d4c4a8;
        border-image: none;
        box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.5), 0 12px 28px var(--vm-shadow);
        border-radius: 4px;
        padding: 10px 12px 4px 12px;
        margin-top: 12px;
    }

    .vm-scroll-card {
        background: linear-gradient(160deg, #2a241c 0%, #1a1612 100%);
        border-radius: 10px;
        padding: 22px 24px;
        color: #f5ecd8 !important;
        border: 1px solid #4a4034;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18);
    }
    .vm-scroll-card h3 {
        color: #f0e6c8 !important;
        font-family: "VM JianDu", "Ma Shan Zheng", "Noto Serif SC", "SimSun", serif !important;
        font-size: 1.5rem;
        letter-spacing: 0.1em;
    }
    .vm-scroll-card p, .vm-scroll-card li { color: #e8dcc8 !important; line-height: 1.75; }
    .vm-scroll-card ul { margin: 0.4em 0 0 1em; }

    [data-testid="stJson"] {
        color: var(--vm-ink-soft) !important;
        background: rgba(255, 252, 245, 0.75) !important;
        border: 1px solid var(--vm-border) !important;
        border-radius: 8px !important;
    }

    /* —— 主视觉 Hero：全页图1 + Hero 图2 见 _inject；VM TitleZh 竖排标题 —— */
    .vm-sr-only {
        position: absolute !important;
        width: 1px !important;
        height: 1px !important;
        padding: 0 !important;
        margin: -1px !important;
        overflow: hidden !important;
        clip: rect(0, 0, 0, 0) !important;
        white-space: nowrap !important;
        border: 0 !important;
    }

    .vm-hero {
        margin: 0 0 0.85rem 0;
        max-width: 100%;
    }
    .vm-hero-card {
        border: 1px solid rgba(196, 181, 154, 0.65);
        border-radius: 12px;
        overflow: visible;
        box-shadow: 0 8px 28px var(--vm-shadow), inset 0 1px 0 rgba(255, 252, 245, 0.65);
        background: linear-gradient(165deg, #faf4e8 0%, #f0e6d4 55%, #e8dcc6 100%);
        backdrop-filter: none;
        -webkit-backdrop-filter: none;
    }
    .vm-hero-topbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.35rem 1rem;
        font-size: 0.68rem;
        letter-spacing: 0.28em;
        text-transform: uppercase;
        color: var(--vm-ink-soft);
        background: linear-gradient(180deg, #e5d8c4 0%, #dccfb8 100%);
        border-bottom: 1px solid var(--vm-border);
        font-family: "Libre Baskerville", "Times New Roman", serif !important;
    }

    .vm-hero-body {
        position: relative;
        min-height: clamp(300px, 46vh, 560px);
        isolation: isolate;
        overflow: visible;
    }
    .vm-hero--compact .vm-hero-body {
        min-height: clamp(160px, 24vh, 300px);
    }

    .vm-hero-paper {
        position: absolute;
        inset: 0;
        background: linear-gradient(165deg, rgba(250, 243, 232, 0.55) 0%, rgba(240, 228, 210, 0.4) 100%);
        z-index: 0;
    }

    .vm-hero-painting {
        position: absolute;
        inset: 0;
        z-index: 1;
        background-color: transparent;
        background-repeat: no-repeat;
        background-position: center center;
        /* 与 _inject 一致：cover；无图时由注入渐变占位 */
        background-size: cover;
    }

    .vm-hero-veil {
        position: absolute;
        inset: 0;
        z-index: 2;
        pointer-events: none;
        background: linear-gradient(
            90deg,
            rgba(250, 243, 230, 0.9) 0%,
            rgba(250, 243, 230, 0.5) 32%,
            rgba(250, 240, 228, 0.36) 58%,
            rgba(242, 234, 218, 0.42) 100%
        );
    }

    .vm-hero-overlay {
        position: absolute;
        inset: 0;
        z-index: 3;
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1.48fr);
        gap: 0.5rem;
        padding: clamp(0.75rem, 2vw, 1.35rem);
        align-items: center;
        pointer-events: none;
        overflow: visible;
    }
    .vm-hero-editorial,
    .vm-hero-stage {
        pointer-events: auto;
    }

    .vm-hero-editorial {
        align-self: center;
        max-width: 100%;
    }
    .vm-hero-ancient-stack {
        position: relative;
        margin-bottom: 0.35rem;
    }
    .vm-hero-ancient {
        display: block;
        font-family: "Libre Baskerville", "Times New Roman", Georgia, serif !important;
        font-size: clamp(1.85rem, 4.2vw, 3.25rem);
        font-weight: 400;
        letter-spacing: 0.14em;
        line-height: 0.95;
        color: rgba(42, 34, 28, 0.5);
        text-transform: uppercase;
        margin: 0;
        padding: 0;
        white-space: nowrap;
    }
    .vm-hero-bracket {
        position: relative;
        margin: -0.85em 0 0 0;
        padding: 0;
        font-family: "Noto Serif SC", "Songti SC", "SimSun", serif !important;
        font-size: clamp(0.82rem, 1.35vw, 1.05rem);
        font-weight: 600;
        color: #141008;
        line-height: 1.45;
        max-width: 22em;
        z-index: 2;
        text-shadow: 0 1px 0 rgba(255, 252, 245, 0.85), 0 0 12px rgba(255, 250, 240, 0.9);
    }
    .vm-hero-tag {
        margin: 0.5rem 0 0 0;
        font-size: 0.78rem;
        color: var(--vm-ink-soft) !important;
        opacity: 0.92;
    }

    .vm-hero-stage {
        position: relative;
        height: 100%;
        min-height: 200px;
        direction: ltr;
        unicode-bidi: isolate;
        padding-right: clamp(0.5rem, 4vw, 2.5rem);
        overflow: visible;
    }
    .vm-hero--compact .vm-hero-stage {
        min-height: 120px;
    }

    .vm-hero-seal-title {
        position: absolute;
        right: clamp(-0.25rem, -0.8vw, 0.35rem);
        top: auto;
        bottom: 0;
        height: auto;
        max-height: none;
        transform: translateX(clamp(0.08rem, 2vw, 1rem));
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-end;
        gap: clamp(0.04em, 0.55vh, 0.1em);
        direction: ltr;
        unicode-bidi: isolate;
        z-index: 6;
        box-sizing: border-box;
        padding: 0;
    }
    .vm-hero--compact .vm-hero-seal-title {
        transform: translateX(clamp(0.06rem, 1.5vw, 0.65rem)) scale(0.78);
        transform-origin: right bottom;
        justify-content: flex-end;
        padding: 0;
        bottom: 0;
    }
    .vm-hero-seal-char {
        font-family: "VM TitleZh", "Noto Serif SC", "SimSun", serif !important;
        font-size: clamp(3.9rem, min(11.5vh, 13.5vw), 10.25rem);
        line-height: 1;
        font-weight: 400;
        color: #141008;
        text-shadow:
            0 0 3px rgba(255, 252, 245, 0.95),
            0 0 22px rgba(255, 250, 240, 0.8),
            0 2px 18px rgba(0, 0, 0, 0.22);
    }
    .vm-hero--compact .vm-hero-seal-char {
        font-size: clamp(2.35rem, min(7.5vh, 9.5vw), 4.5rem);
    }

    @media (prefers-reduced-motion: reduce) {
        .vm-hero-card {
            backdrop-filter: none !important;
            -webkit-backdrop-filter: none !important;
        }
    }

    @media (max-width: 900px) {
        .vm-hero-overlay {
            grid-template-columns: 1fr;
        }
        .vm-hero-stage {
            min-height: 220px;
        }
        .vm-hero-seal-title {
            right: clamp(-0.15rem, -0.5vw, 0.2rem);
            transform: translateX(clamp(0.06rem, 1.8vw, 0.75rem));
            justify-content: flex-end;
            bottom: 0;
        }
        .vm-hero-seal-char {
            font-size: clamp(3.2rem, min(10vh, 12vw), 7.5rem);
        }
        .vm-hero--compact .vm-hero-seal-title {
            transform: translateX(clamp(0.04rem, 1.2vw, 0.5rem)) scale(0.72);
            transform-origin: right bottom;
        }
    }
</style>
""", unsafe_allow_html=True)

_inject_hero_assets_css()
_inject_texture_panel_css()
_inject_primary_button_css()
_inject_sidebar_compile_button_css()
_debug_button_texture_captions()
_inject_sidebar_scroll_tooltip_css()

# ==================== 侧边栏 ====================
with st.sidebar:
    st.markdown(
        '<div class="vm-sidebar-brand"><h1 class="vm-sidebar-brand-title">审美实验室</h1></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="vm-sidebar-input-panel">', unsafe_allow_html=True)
    st.subheader("输入文本")
    st.caption("点选示例可一键填入整句")
    _ex1, _ex2, _ex3 = st.columns(3)
    with _ex1:
        if st.button("春江潮水", key="pill_cjcs", use_container_width=True, type="secondary"):
            st.session_state.verse_input = "春江潮水连海平，海上明月共潮生"
    with _ex2:
        if st.button("蓦然回首", key="pill_mrh", use_container_width=True, type="secondary"):
            st.session_state.verse_input = "众里寻他千百度，蓦然回首，那人却在，灯火阑珊处"
    with _ex3:
        if st.button("坐看云起", key="pill_zkyq", use_container_width=True, type="secondary"):
            st.session_state.verse_input = "行到水穷处，坐看云起时"
    input_text = st.text_area(
        "请输入诗句、短句或任何文字",
        key="verse_input",
        height=120,
        placeholder="如：大漠孤烟直",
    )
    st.caption(f"当前约 {len(input_text)} 字")
    if len((input_text or "").strip()) == 1:
        st.caption("一字境：可试补为半联；或点下句随机缀一联。")
        if st.button("随机缀一联", key="vm_one_char_snip"):
            _tails = (
                "接天涯，意随云水共迢遥。",
                "落人间，半随烟雨半随山。",
                "入丹青，半分月色半分青。",
            )
            st.session_state.verse_input = (input_text or "").strip() + random.choice(_tails)
    st.markdown("</div>", unsafe_allow_html=True)

    st.subheader("参数调节")
    abstraction = st.slider(
        "抽象程度",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        help="近物远意：0 偏具象如实写生，1 偏抽象取神；中平如兼工带写。",
    )
    
    tension = st.slider(
        "视觉张力", 
        min_value=0.0,
        max_value=1.0,
        value=0.7,
        help="浓淡相生：0 如淡墨远岚，1 如焦墨疾风；中道则气韵相济。",
    )

    color_tendency = st.slider(
        "色彩倾向（冷↔暖）",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        help="冷暖自知：0 偏青灰冷韵，1 偏赭黄暖意；中则四时调和。",
    )
    density_spacing = st.slider(
        "疏密 / 留白（满↔疏）",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        help="计白当黑：0 景密如织，1 疏可走马；中则虚实有度。",
    )
    era_tone = st.slider(
        "古意 ←——→ 当代（右滑更当代）",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        help="古今一脉：0 尚高古简淡，1 尚当代表达；中则借古开今。",
    )
    st.caption("0 偏古 · 1 偏今：数值越大越偏现代表达与镜头感。")
    narrative_symbolism = st.slider(
        "叙事 / 象征强度",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        help="象外之象：0 偏直写场景，1 偏隐喻象征；中则情景相生。",
    )
    with st.expander("当前墨法提要", expanded=False):
        st.caption(
            _ink_preview_summary(
                abstraction, tension, color_tendency, density_spacing, era_tone, narrative_symbolism
            )
        )
    
    st.divider()
    
    st.subheader("系统状态")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("模型", model_name)
    with col2:
        st.metric("API 状态", "正常" if api_key else "未配置")
    st.divider()
    
    # 操作按钮
    col1, col2 = st.columns(2)
    with col1:
        run_btn = st.button("执行编译", type="primary", use_container_width=True, key="vm_run_compile")
    with col2:
        test_btn = st.button("测试连接", use_container_width=True)
    
    st.caption(f"版本 1.0 | {datetime.now().strftime('%Y-%m-%d')}")

# ==================== 主界面 ====================
_hero_compact = st.session_state.compiled_result is not None
st.markdown(_render_hero_html(_hero_compact), unsafe_allow_html=True)

_asset_hints = []
if not _hero_title_font_path():
    _asset_hints.append(
        "主标题字体：优先 static/fonts/方正瘦金书繁体.TTF；备选 方正字迹-吕建德行楷简体.TTF、丛台-肖进生丛台体.TTF、方正章草简体.TTF（商用请自行确认授权）"
    )
if not _jiandu_font_path():
    _asset_hints.append(
        "简牍标题字体：可选 static/fonts/方正字迹-俊坡简牍繁体.TTF（侧栏与核心价值卡片标题，商用请自行确认授权）"
    )
if not _han_global_bg_path():
    _asset_hints.append("全页背景：可放 static/han_xizai1.png 或 static/han_xizai 1.png")
if not _han_hero_panel_path():
    _asset_hints.append("Hero 背景：可放 static/han_xizai2.png")
if not _sidebar_texture_path():
    _asset_hints.append("侧栏整栏底纹：可放 static/fonts/Texture.png 或 static/Texture.png")
if not _welcome_sn_path():
    _asset_hints.append(
        "欢迎区底图（优先）：可放 static/sn.png 或 static/fonts/sn.png；无 sn 时将回退 TIF分段等素材"
    )
if not _sidebar_deco_bitmap_path():
    _asset_hints.append(
        "侧栏装饰：浏览器无法直接使用 PSD；请将 JPG分段 (9) 导出为同目录下的 PNG/JPG 后再加载"
    )
_welcome_bg = _welcome_panel_bg_path()
if not _welcome_sn_path() and not _welcome_bg:
    _asset_hints.append(
        "欢迎区次选背景：可放 static/fonts/TIF分段 (11).png（推荐）或 .tiff；若 TIF 不显示请改用 PNG"
    )
elif not _welcome_sn_path() and _welcome_bg and _welcome_bg.lower().endswith((".tif", ".tiff")):
    _asset_hints.append("欢迎区当前为 TIF 位图：若浏览器不显示背景，请导出 PNG 或添加 sn.png")
_debug_assets = os.environ.get("VERSEMESH_DEBUG", "").strip().lower() in ("1", "true", "yes")
if _asset_hints and _debug_assets:
    st.caption(" · ".join(_asset_hints))

# 初始状态展示
if not run_btn and not test_btn and st.session_state.compiled_result is None:
    col1, col2 = st.columns([3, 2])
    
    with col1:
        st.markdown(
            """<div class="vm-welcome-panel">

### 欢迎使用

**VerseMesh** 尝试在「文」与「象」之间架起一座小桥，它能够：

- **会意**：读诗句与短句，揣摩意境层次
- **量化**：把难以言说的审美，落成可调参数
- **成图**：为 AI 绘图准备更贴题的中文与英文提示

### 使用指南

1. 在左侧输入诗句或短句
2. 调节「抽象程度」「视觉张力」及色彩、疏密、古意、叙事等滑块
3. 点击 **执行编译**
4. 查看参数、JSON 与出图提示

### 示例

- 「春江潮水连海平，海上明月共潮生」
- 「众里寻他千百度，蓦然回首，那人却在，灯火阑珊处」
- 「行到水穷处，坐看云起时」

</div>""",
            unsafe_allow_html=True,
        )
    
    with col2:
        st.markdown("""
        <div class="vm-scroll-card">
            <h3>核心价值</h3>
            <p>以辞章为引，以参数为骨，让「意境」在画面里有一席之地。</p>
            <h3 style="margin-top: 1rem;">技术栈</h3>
            <ul>
                <li>智谱 GLM 文本解析</li>
                <li>百炼 Wan 图像生成（可选）</li>
                <li>Streamlit 交互 · 结构化 JSON 输出</li>
            </ul>
            <p style="margin-top:1rem;font-size:0.78rem;opacity:0.88;line-height:1.55;">方正等字库之商用与分发，请使用者自行确认授权。</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(
            '<div class="vm-hint" role="status"><div class="vm-hint-inner"><strong>提示</strong>：首次使用请先点击「测试连接」确认 API 可用。</div></div>',
            unsafe_allow_html=True,
        )

# ==================== 功能逻辑 ====================
# 测试连接功能
if test_btn:
    _vm_hint("正在测试与智谱 API 的连通性……")
    
    try:
        test_response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "请回复'VerseMesh 审美编译器连接正常。'"}],
            max_tokens=20
        )
        
        st.balloons()
        st.success("API 连接测试成功。")
        st.markdown(f"""
        <div class='success-box'>
            <strong>模型回复：</strong><br>
            {test_response.choices[0].message.content}
        </div>
        """, unsafe_allow_html=True)
        
    except APIAuthenticationError:
        st.error("连接测试失败：401 身份验证失败（API Key 无效、过期或已被禁用）")
        _vm_hint("请在智谱开放平台重新生成 API Key，并更新到项目根目录 .env 的 ZHIPUAI_API_KEY。")
    except APIStatusError as e:
        st.error(f"连接测试失败：{e}")
        _vm_hint("请检查模型名称是否可用、账号是否有该模型权限，以及余额/配额是否充足。")
    except Exception as e:
        st.error(f"连接测试失败：{e}")
        _vm_hint("请检查：1) .env 中的 API 密钥 2) 网络 3) 账户额度")

# 执行编译功能
if run_btn and input_text:
    if not input_text.strip():
        st.warning("请输入一些文字内容。")
        st.stop()
    
    with st.spinner("钤印会意，墨色渐清……"):
        st.markdown(_vm_wait_curtain_html("compile"), unsafe_allow_html=True)
        progress_bar = st.progress(0)
        for i in range(100):
            time.sleep(0.01)
            progress_bar.progress(i + 1)
    
    # 调用核心函数
    result = extract_aesthetic_params(
        input_text,
        abstraction,
        tension,
        color_tendency,
        density_spacing,
        era_tone,
        narrative_symbolism,
    )
    
    if result:
        st.session_state.compiled_result = result
        st.session_state.compiled_input_text = input_text
        st.session_state.generated_image_url = None
        st.session_state.last_image_prompt = ""
        st.session_state.last_image_meta = {}
        st.balloons()
        st.success("审美编译完成。")
        st.caption(_vm_random_compile_seal_line())
        _ct = (result.get("core_theme") or "").strip()
        if _ct:
            st.markdown(
                f'<p class="vm-repro-bar"><strong>诗眼提要</strong>：{html.escape(_ct)}</p>',
                unsafe_allow_html=True,
            )
    else:
        st.error("编译失败，请查看上方错误信息。")

# 展示会话中保存的编译结果（按钮触发重跑后仍可见）
if st.session_state.compiled_result:
    result = st.session_state.compiled_result
    input_text_for_image = st.session_state.compiled_input_text or input_text

    st.write("---")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"""
        <div class='param-card'>
            <h3>核心主题</h3>
            <h2 style='margin: 0.35rem 0 0 0; font-size: 1.65rem;'>{result.get('core_theme', 'N/A')}</h2>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class='param-card'>
            <h3>艺术家参考</h3>
            <p style='font-size: 1.05rem; margin-top: 0.5rem;'>{result.get('artist_reference', 'N/A')}</p>
        </div>
        """, unsafe_allow_html=True)

    st.subheader("色彩面板")
    if "color_palette" in result:
        cp = result["color_palette"]
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("主色调", cp.get("primary_tone", "N/A"))
        with col2:
            st.slider("饱和度", 1, 10, cp.get("saturation", 5), disabled=True)
        with col3:
            st.slider("明度", 1, 10, cp.get("brightness", 5), disabled=True)

    st.subheader("情绪向量")
    if "emotional_vector" in result:
        ev = result["emotional_vector"]
        col1, col2, col3 = st.columns(3)
        with col1:
            st.progress(ev.get("tranquility", 50) / 100, text=f"宁静感 {ev.get('tranquility', 50)}%")
        with col2:
            st.progress(ev.get("grandeur", 50) / 100, text=f"宏大感 {ev.get('grandeur', 50)}%")
        with col3:
            st.progress(ev.get("ethereality", 50) / 100, text=f"空灵感 {ev.get('ethereality', 50)}%")

    if "composition" in result:
        st.subheader("构图分析")
        comp = result["composition"]
        _vm_hint(f"地平线构图：{comp.get('horizon_line', 'N/A')}")
        _vm_hint(f"视觉平衡：{comp.get('visual_balance', 'N/A')}")

    st.write("---")
    st.subheader("AI 直接生成图像")
    st.markdown("调整参数后点击按钮，生成结果会直接显示在下方（无需再切换标签）。")
    c1, c2 = st.columns(2)
    with c1:
        image_size = st.selectbox(
            "图像尺寸",
            options=["1344x768", "1024x1024", "768x1344"],
            index=0,
            key="image_size",
        )
    with c2:
        image_style = st.selectbox(
            "图像风格",
            options=["natural", "vivid"],
            index=0,
            key="image_style",
        )
    strict_semantics = st.checkbox(
        "语义贴合优先（推荐开启）",
        value=True,
        key="strict_semantics",
        help="开启后会更严格地围绕诗句语义出图，减少风格化跑题。",
    )
    st.checkbox(
        "已粗看句意与滑块（可选自警，不挡出图）",
        value=False,
        key="vm_image_preflight",
        help="仅作提醒；勾选与否不影响提交。",
    )

    if st.button("直接生成图像", type="primary", key="generate_image_btn"):
        with st.spinner("丹青将成，稍候片时……"):
            st.markdown(_vm_wait_curtain_html("image"), unsafe_allow_html=True)
            image_url, used_prompt = generate_image_with_wan(
                result,
                input_text_for_image,
                abstraction_level=abstraction,
                tension_level=tension,
                size=image_size,
                style=image_style,
                strict_semantics=strict_semantics,
                color_tendency=color_tendency,
                density_spacing=density_spacing,
                era_tone=era_tone,
                narrative_symbolism=narrative_symbolism,
            )
        st.session_state.generated_image_url = image_url
        st.session_state.vm_balloons_next_image = bool(image_url)
        st.session_state.last_image_prompt = used_prompt or ""
        st.session_state.last_image_meta = {
            "size": image_size,
            "style": image_style,
            "strict_semantics": strict_semantics,
            "abstraction": abstraction,
            "tension": tension,
            "color_tendency": color_tendency,
            "density_spacing": density_spacing,
            "era_tone": era_tone,
            "narrative_symbolism": narrative_symbolism,
            "wan_model": image_model_name,
            "glm_model": model_name,
        }

    if st.session_state.generated_image_url:
        meta = st.session_state.get("last_image_meta", {})
        size_label = meta.get("size", image_size)
        style_label = meta.get("style", image_style)
        if st.session_state.vm_balloons_next_image:
            st.session_state.vm_balloons_next_image = False
            st.balloons()
        st.success(_vm_image_done_line(str(size_label), str(style_label)))
        _m = meta
        _wan = html.escape(str(_m.get("wan_model", image_model_name)))
        _glm = html.escape(str(_m.get("glm_model", model_name)))
        _sz = html.escape(str(size_label))
        _st = html.escape(str(style_label))
        _repro_one = (
            f"万相 {_wan} · {_sz} · {_st} · 语义{'开' if _m.get('strict_semantics', strict_semantics) else '关'} · "
            f"抽象{float(_m.get('abstraction', abstraction)):.2f} 张力{float(_m.get('tension', tension)):.2f} · "
            f"色{float(_m.get('color_tendency', color_tendency)):.2f} 疏密{float(_m.get('density_spacing', density_spacing)):.2f} · "
            f"古意{float(_m.get('era_tone', era_tone)):.2f} 象征{float(_m.get('narrative_symbolism', narrative_symbolism)):.2f} · "
            f"GLM {_glm}"
        )
        st.markdown(
            f'<p class="vm-repro-bar">{_repro_one}</p>',
            unsafe_allow_html=True,
        )
        _repro_code = (
            "WAN_MODEL={}\nGLM_MODEL={}\nSIZE={}\nSTYLE={}\nSTRICT_SEMANTICS={}\n"
            "abstraction={:.4f}\ntension={:.4f}\ncolor_tendency={:.4f}\ndensity_spacing={:.4f}\n"
            "era_tone={:.4f}\nnarrative_symbolism={:.4f}".format(
                _m.get("wan_model", image_model_name),
                _m.get("glm_model", model_name),
                size_label,
                style_label,
                _m.get("strict_semantics", strict_semantics),
                float(_m.get("abstraction", abstraction)),
                float(_m.get("tension", tension)),
                float(_m.get("color_tendency", color_tendency)),
                float(_m.get("density_spacing", density_spacing)),
                float(_m.get("era_tone", era_tone)),
                float(_m.get("narrative_symbolism", narrative_symbolism)),
            )
        )
        _copy_a, _copy_b = st.columns(2)
        with _copy_a:
            _vm_clipboard_copy_button("复制可复现参数", _repro_code)
        with _copy_b:
            _poem_eye = (
                (input_text_for_image or "").strip()
                + "\n\n诗眼："
                + (result.get("core_theme") or "").strip()
            )
            _vm_clipboard_copy_button("复制诗句与诗眼", _poem_eye)
        with st.expander("可复现参数（复制用）", expanded=False):
            st.code(_repro_code, language="text")
        st.markdown("<div class='image-result-panel'>", unsafe_allow_html=True)
        st.image(
            st.session_state.generated_image_url,
            caption=f"VerseMesh AI 生成图（{size_label}, {style_label}）",
            use_container_width=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        _img_url = html.escape(st.session_state.generated_image_url, quote=True)
        st.markdown(
            f'<p style="margin:0.35rem 0 0 0;"><a class="vm-open-image-link" href="{_img_url}" '
            f'target="_blank" rel="noopener noreferrer">在新标签页打开原图</a></p>',
            unsafe_allow_html=True,
        )
    elif st.session_state.last_image_prompt:
        st.warning("图像生成未返回可用图片链接，请稍后重试。")

    _lp = st.session_state.get("last_image_prompt") or ""
    _snip = _poetic_snippet_from_last_prompt(_lp)
    if _snip:
        with st.expander("上次出图诗性提要（截选）", expanded=False):
            st.markdown(
                f'<p class="vm-repro-bar">{html.escape(_snip)}</p>',
                unsafe_allow_html=True,
            )

    with st.expander("查看用于生成图像的提示词", expanded=False):
        st.code(st.session_state.last_image_prompt if st.session_state.last_image_prompt else "无提示词", language="text")

    with st.expander("完整参数 JSON", expanded=True):
        st.json(result)

    with st.expander("兼容模式：Midjourney 提示词", expanded=False):
        mj_prompt = generate_midjourney_prompt(result)
        st.code(mj_prompt, language="text")

# ==================== 页脚 ====================
st.write("---")
col1, col2, col3 = st.columns(3)
with col1:
    st.caption("**VerseMesh** · 诗意晶格")
with col2:
    st.caption("智谱 GLM · 百炼 Wan（可选）")
with col3:
    st.caption(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

_sig_line = _VM_FOOTER_SIGS[datetime.now().toordinal() % len(_VM_FOOTER_SIGS)]
st.markdown(
    f'<p class="vm-footer-sig">{html.escape(_sig_line)}</p>',
    unsafe_allow_html=True,
)

st.caption("""
**免责声明**：本工具仅供学习与演示；生成提示词与图像仅供参考，实际效果受模型与参数影响，请自行斟酌使用。
""")