from aihub_common import spoken_text


def test_removes_emoji_clusters_without_removing_chinese_or_numbers():
    assert spoken_text('你好呀！😊👨‍👩‍👧‍👦👍🏽🇨🇳❤️') == '你好呀！'
    assert spoken_text('第1️⃣题，答案是2。') == '第1题，答案是2。'


def test_keeps_intended_descriptions_as_normal_language():
    assert spoken_text('这个符号表示脸颊泛红的笑脸。') == '这个符号表示脸颊泛红的笑脸。'
    assert spoken_text('温度是26℃，价格是¥50。') == '温度是26℃，价格是¥50。'


def test_emoji_only_has_no_spoken_content():
    assert spoken_text(' 😊\u200d\ufe0f ') == ''


def test_emoji_is_replaced_by_space_so_words_do_not_glue():
    assert spoken_text('你好😊世界') == '你好 世界'


def test_none_safe_contract_is_not_required():
    # spoken_text takes a str; callers guard against None before calling. This
    # test pins the fact that an empty string is the identity element.
    assert spoken_text('') == ''
