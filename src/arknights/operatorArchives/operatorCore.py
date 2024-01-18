import asyncio

from dataclasses import dataclass
import os
import re
import uuid
from amiyabot import GroupConfig, event_bus

from core import bot as main_bot
from core import Message, AmiyaBotPluginInstance, Requirement
from core.resource.arknightsGameData import ArknightsGameData
from core.util import any_match, find_most_similar, get_index_from_text, remove_punctuation

from .operatorInfo import OperatorInfo, curr_dir

default_level = 3


class OperatorPluginInstance(AmiyaBotPluginInstance):
    def install(self):
        asyncio.create_task(OperatorInfo.init_operator())
        asyncio.create_task(OperatorInfo.init_skins_keywords())
        asyncio.create_task(OperatorInfo.init_stories_keywords())

    def load(self):
        self.image_to_html_map = {}

        blm_lib = main_bot.plugins['amiyabot-blm-library']
                    
        if blm_lib is None:
            bot.debug_log("未加载blm库，无法使用AI查询")
            return
        
        # 此处在最外侧引用会有循环引用问题，为了快速验证原型，这里偷懒没有处理，而是延后引用
        from .operatorData import OperatorData

        @blm_lib.register_blm_function
        async def get_operator_info(operator_name:str) -> dict:
            """
            该函数可以用于获取干员的信息，包括其属性，技能等等，同时还能获取其对应的图片。

            :param operator_name: 干员的名称，例如“阿米娅”，必须为中文。
            :type operator_name: str

            :return: 一个字典，包含两个元素，“info”是包含干员数据的结构化字典。“image”是一个url，包含了一张排版好干员信息的图片，可供展示。
            :rtype: bool
            """
                
            info = search_info_raw(operator_name, [operator_name], source_keys=['name'])
            
            result, tokens = await OperatorData.get_operator_detail(info)
            
            if result:

                detail_text = ""

                detail_text += "技力每秒恢复1点\n"

                stories = result.stories()

                real_name = await ArknightsGameData.get_real_name(result.origin_name)
                detail_text += f'干员代号:{result.name} 干员真名:{real_name}\n'
                
                race_match = re.search(r'【种族】(.*?)\n', next(story["story_text"] for story in stories if story["story_title"] == "基础档案"))
                if race_match:
                    race = race_match.group(1)
                else:
                    race = "未知"
                detail_text = detail_text + f'职业:{result.type} 种族:{race}\n'


                detail_text += next(story["story_text"]+"\n" for story in stories if story["story_title"] == "客观履历")

                opt_detail = result.detail()[0]

                detail_text += f'最大生命:{opt_detail["maxHp"]} 攻击力:{opt_detail["atk"]} 防御力:{opt_detail["def"]} 法术抗性:{opt_detail["magicResistance"]}% 攻击间隔:{opt_detail["baseAttackTime"]}秒\n'

                detail_text +=f'干员特性:{opt_detail["operator_trait"]}\n'

                talents = result.talents()

                talent_txt=""
                for i, talent in enumerate(talents, start=1):
                    talent_name = talent["talents_name"]
                    talent_desc = talent["talents_desc"]
                    talent_txt += f"{i}天赋-{talent_name}:{talent_desc}"
                    if i < len(talents):
                        talent_txt += "。 "

                detail_text += f"{talent_txt}\n"

                skills, skills_id, skills_cost, skills_desc = result.skills()

                for i in range(1, 4):
                    matching_skill = next((skill for skill in skills if skill["skill_index"] == i), None)
                    
                    skill_txt = ""

                    if matching_skill:
                        skill_txt=f"{i}技能:"
                        skill_txt = f"{matching_skill['skill_name']} "

                        skill_desc = skills_desc[matching_skill['skill_no']]

                        best_level = max([desc['skill_level'] for desc in skill_desc])
                        best_desc = next((desc for desc in skill_desc if desc['skill_level'] == best_level), None)

                        desc_text = re.sub(r'\[cl (.*?)@#.*? cle\]', lambda x: x.group(1), best_desc['description'])

                        skill_txt+=f"初始技力:{best_desc['sp_init']} 技力消耗:{best_desc['sp_cost']} 持续时间:{best_desc['duration']} {desc_text}"
                        
                        skill_txt+="\n"
                    
                    detail_text += skill_txt


                image_url = "https://res.amiyabot.com/plugins/amiyabot-arknights-operator/"+uuid.uuid4().hex+".png"
                bot.image_to_html_map = {image_url:{
                    "template":os.path.abspath(f'{curr_dir}/template/operatorInfo.html'),
                    "data":result
                }}

                return {"info":detail_text,"image":image_url}
            else:
                return None

    def uninstall(self):
        event_bus.unsubscribe('gameDataInitialized', update)


@event_bus.subscribe('gameDataInitialized')
def update(_):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        bot.install()


bot = OperatorPluginInstance(
    name='明日方舟干员资料',
    version='4.1.1',
    plugin_id='amiyabot-arknights-operator',
    plugin_type='official',
    description='查询明日方舟干员资料',
    document=f'{curr_dir}/README.md',
    instruction=f'{curr_dir}/README_USE.md',
    global_config_schema=f'{curr_dir}/config_schema.json',
    global_config_default=f'{curr_dir}/config_default.yaml',
    requirements=[Requirement('amiyabot-arknights-gamedata', official=True)],
)
bot.set_group_config(GroupConfig('operator', allow_direct=True))

@dataclass
class OperatorSearchInfo:
    name: str = ''
    skin_key: str = ''
    group_key: str = ''
    voice_key: str = ''
    story_key: str = ''


class FuncsVerify:
    @classmethod
    async def level_up(cls, data: Message):
        info = search_info(data, source_keys=['name'])

        condition = any_match(data.text, ['精英', '专精'])
        condition2 = info.name and '材料' in data.text

        return bool(condition or condition2), (6 if condition2 else 2), info

    @classmethod
    async def operator(cls, data: Message):
        info = search_info(data, source_keys=['name'])

        if bot.get_config('searchSetting')['needPrefix'] and '查询' not in data.text:
            return False

        return bool(info.name), default_level if info.name != '阿米娅' else 0, info

    @classmethod
    async def group(cls, data: Message):
        info = search_info(data, source_keys=['group_key'])

        return bool(info.group_key), default_level + 1, info


def search_info(data: Message, source_keys: list = None):
    limit_length = bot.get_config('searchSetting')['lengthLimit']

    if len(data.text_words) > int(limit_length):
        return OperatorSearchInfo()

    return search_info_raw(data.text, source_keys)

def search_info_raw(text:str, words:list , source_keys: list = None):
    info_source = {
        'name': OperatorInfo.operator_list + list(OperatorInfo.operator_en_name_map.keys()),
        'skin_key': list(OperatorInfo.skins_map.keys()),
        'group_key': list(OperatorInfo.operator_group_map.keys()),
        'voice_key': OperatorInfo.voice_keywords,
        'story_key': OperatorInfo.stories_keywords,
    }

    info = OperatorSearchInfo()
    similar_mode = bot.get_config('searchSetting')['similarMode']

    match_method = find_most_similar if similar_mode else get_longest

    if source_keys is None:
        return info

    for key_name in source_keys:
        res = match_method(text, info_source[key_name])
        if res and remove_punctuation(res) in remove_punctuation(text):
            setattr(info, key_name, res)

            if key_name == 'name':
                if info.name in OperatorInfo.operator_en_name_map:
                    info.name = OperatorInfo.operator_en_name_map[info.name]

                if info.name not in words:
                    continue

                if info.name == '阿米娅':
                    for item in ['阿米娅', 'amiya']:
                        t = text.lower()
                        if t.startswith(item) and t.count(item) == 1:
                            info.name = match_method(text.replace(item, ''), info_source[key_name])

    return info

def get_longest(text: str, items: list):
    res = ''
    for item in items:
        if item in text and len(item) >= len(res):
            res = item

    return res


def get_index(text: str, array: list):
    for item in OperatorInfo.operator_contain_digit_list:
        text = text.lower().replace(item, '')

    return get_index_from_text(text, array)
