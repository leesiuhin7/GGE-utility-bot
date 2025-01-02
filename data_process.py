import json
from typing import Any



class _AttackWarning:

    def __init__(self) -> None:
        pass


    def decode_message(
        self, 
        message: str
    ) -> list[tuple[Any, ...]] | None:
        
        start = message.find("{")
        if start == -1:
            return
        
        data = json.loads(message[start:-1])

        info_list = []
        attack_count = len(data["M"])
        for i in range(attack_count):
            try:
                info = self._unpack_data(data["M"][i])
            except:
                continue

            if info is not None:
                info_list.append(info)

        return info_list
    

    def format_warning(self, info: tuple[Any, ...]) -> str:
        message = " ".join([
            "@everyone",
            f"incoming attack in approx.",
            self._seconds2compound(info[0]),
            f"at \"{info[5]}\" ({info[1]}:{info[2]})",
            f"from \"{info[6]}\" ({info[3]}:{info[4]})"
        ])
        return message
    

    def _unpack_data(
        self, 
        data: dict
    ) -> tuple[Any, ...] | None:
        
        if not ("GS" in data or "GA" in data):
            return
        
        atk_id = data["M"]["MID"]
        remaining_time = data["M"]["TT"] - data["M"]["PT"]

        target_x = data["M"]["TA"][1]
        target_y = data["M"]["TA"][2]
        target_name = data["M"]["TA"][10]

        attacker_x = data["M"]["SA"][1]
        attacker_y = data["M"]["SA"][2]
        attacker_name = data["M"]["SA"][10]

        info = (
            remaining_time,
            target_x,
            target_y,
            attacker_x,
            attacker_y,
            target_name,
            attacker_name,
            atk_id
        )
        return info
    

    def _seconds2compound(self, seconds: float) -> str:
        h = seconds // 3600
        m = seconds // 60 % 60
        s = seconds // 1 % 60
        if h != 0:
            return f"{h}h {m}m {s}s"
        elif m != 0:
            return f"{m}m {s}s"
        else:
            return f"{s}s"
        


class _StormFort:

    def __init__(self) -> None:
        pass


    def decode_message(
        self,
        message: str
    ) -> list[tuple[int, int, int]] | None:
        
        start = message.find("{")
        if start == -1:
            return
        
        data = json.loads(message[start:-1])

        stort_fort_list = []
        castle_count = len(data["AI"])
        for i in range(castle_count):
            try:
                castle_info = self._unpack_data(data["AI"][i])
            except:
                continue

            if castle_info is not None:
                stort_fort_list.append(castle_info)

        return stort_fort_list
    

    def translate_criterias(
        self,
        criterias: list[str]
    ) -> list[int]:
        
        translated = []
        if "40" in criterias:
            translated.append(10)
        if "50" in criterias:
            translated.append(11)
        if "60" in criterias:
            translated.append(7)
            translated.append(12)
        if "70" in criterias:
            translated.append(8)
            translated.append(13)
        if "80" in criterias:
            translated.append(9)
            translated.append(14)

        if translated == []:
            translated = [10, 11, 7, 12, 8, 13, 9, 14]

        return translated
    

    def translate_strength_type(
        self, 
        strength_type: int
    ) -> str | None:
        
        translate_dict = {
            10: "lvl 40",
            11: "lvl 50",
            7: "lvl 60 (weak)",
            12: "lvl 60 (strong)",
            8: "lvl 70 (weak)",
            13: "lvl 70 (strong)",
            9: "lvl 80 (weak)",
            14: "lvl 80 (strong)"
        }
        return translate_dict.get(strength_type)
    

    def format_storm_forts(
        self, 
        storm_forts: list[tuple[int, int, int]],
        max_lines: int
    ) -> list[str]:

        index = 0
        output_texts = []
        while index < len(storm_forts):
            info_texts = []
            for _ in range(max_lines):
                if index >= len(storm_forts):
                    break

                x = storm_forts[index][0]
                y = storm_forts[index][1]
                lvl = self.translate_strength_type(
                    storm_forts[index][2]
                )
                index += 1

                info_texts.append(
                    f"{lvl} storm fort ({x}:{y})"
                )

            output_texts.append("\n".join(info_texts))

        return output_texts



    def _unpack_data(
        self,
        data: list
    ) -> tuple[int, int, int] | None:
        
        if data[0] != 25:
            return
        
        x_pos = data[1]
        y_pos = data[2]
        strength_type = data[5]

        info = (
            x_pos,
            y_pos,
            strength_type
        )
        return info


attack_warning = _AttackWarning()
storm_fort = _StormFort()