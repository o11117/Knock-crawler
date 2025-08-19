# money_parser.py
import re


def to_won(raw_text: str) -> int:
    """'1억 2,500만' 같은 문자열을 숫자(원 단위)로 변환합니다."""
    if not raw_text:
        return 0

    # 불필요한 문자 제거
    clean_text = re.sub(r"[^0-9억만,.]", "", raw_text)

    try:
        total_won = 0
        if '억' in clean_text:
            parts = clean_text.split('억')
            # '억' 단위 처리
            if parts[0]:
                total_won += float(parts[0].replace(',', '')) * 100000000

            # '만' 단위 처리
            if len(parts) > 1 and '만' in parts[1]:
                man_part = parts[1].replace('만', '').replace(',', '')
                if man_part:
                    total_won += float(man_part) * 10000

        elif '만' in clean_text:
            man_value = clean_text.replace('만', '').replace(',', '')
            total_won += float(man_value) * 10000

        else:  # 억, 만 단위가 없는 경우
            return int(re.sub(r'[^0-9]', '', clean_text))

        return int(total_won)
    except (ValueError, IndexError):
        return 0