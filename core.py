import random
from collections import defaultdict

RANK_VALUE = {'A': 1, '2': 2, '3': 3, '4': 4, '5': 5,
              '6': 6, '7': 7, '8': 8, '9': 9, '10': 10,
              'J': 11, 'Q': 12, 'K': 13}


class Card:
    def __init__(self, suit, rank, name, type):
        self.suit = suit
        self.rank = rank
        self.name = name
        self.type = type

    def __str__(self):
        return self.suit + self.rank + self.name

    def color(self):
        if self.suit in "♠♣":
            return "black"
        else:  # self.suit in "♥♦":
            return "red"

    def rank_value(self):
        return RANK_VALUE[self.rank]


def color(cards):
    colors = {card.color() for card in cards}
    if len(colors) == 1:
        return colors.pop()
    else:
        return "no_color"


class Event:
    def __init__(self, who, what, cause=None, **kwargs):
        self.who = who
        self.what = what
        self.cause = cause  # Can build a chain of events through causality
        self.args = kwargs

    def __str__(self):
        # return f"Event(who={self.who}, what={self.what}, cause={self.cause})"
        return f"{self.what}({self.who}, {', '.join(f'{key}={val}' for key, val in self.args.items())}) <- {self.cause}"


class DamageEvent(Event):
    def __init__(self, who, whom, n=1, cause=None, type=None):
        super(DamageEvent, self).__init__(who, "damage", cause)
        self.whom = whom
        self.n = n
        self.type = type

    def __str__(self):
        return f"{self.what}({self.who}, {self.whom}) <- {self.cause}"


class UseCardEvent(Event):
    def __init__(self, who, card_type, cards, targets=None, cause=None):
        super(UseCardEvent, self).__init__(who, "use_card", cause)
        self.card_type = card_type
        self.cards = cards
        if targets is None:
            targets = []
        self.targets = targets

    def __str__(self):
        return f"{self.what}({self.who}, {self.card_type.__name__}) <- {self.cause}"


class UseSkillEvent(Event):
    def __init__(self, who, skill, targets=None, cause=None):
        super(UseSkillEvent, self).__init__(who, "use_skill", cause)
        self.skill = skill
        if targets is None:
            targets = []
        self.targets = targets

    def __str__(self):
        return f"{self.what}({self.who}, {self.skill.__class__.__name__}) <- {self.cause}"


class LoseCardEvent(Event):
    def __init__(self, who, card, zone, type="弃置", cause=None):
        super(LoseCardEvent, self).__init__(who, "lose_card", cause)
        self.card = card
        self.zone = zone
        self.type = type

    def __str__(self):
        return f"{self.what}({self.who}, {self.card}, {self.zone}, {self.type}) <- {self.cause}"


class CardType:
    class_ = None
    n_targets = 1  # 南蛮入侵, 万箭齐发, 五谷丰登, 桃园结义 have no constraint on number of targets (n_targets = None)
                   # 铁索连环 has n_target = 2; 闪 and 无懈可击 have n_target = 0
                   # All other cards have n_target = 1
    can_recast = False

    @classmethod
    def use_range(cls, player, cards):
        return None  # 顺手牵羊 and 兵粮寸断 have a use range of 1
        # 杀 has a use range of 1 (or the range of the equipped weapon)
        # All other cards have no use range constraint (use_range = None)

    @classmethod
    def target_legal(cls, player, target, cards):
        game = player.game
        use_card_event = UseCardEvent(player, cls, cards)
        event = Event(target, "test_target_prohibited", use_card_event)
        prohibited = game.trigger_skills(event, False)  # 空城, 谦逊, 帷幕
        if prohibited:
            return False
        event = Event(player, "modify_use_range", card_type=cls, cards=cards)
        use_range = game.trigger_skills(event, cls.use_range(player, cards))  # 奇才, 天义, 断粮
        if use_range is None:
            return True
        return use_range >= game.distance(player, target)

    @classmethod
    def can_use(cls, player, cards):
        game = player.game
        event = Event(player, "test_use_prohibited", card_type=cls, cards=cards)
        prohibited = game.trigger_skills(event, False)  # 天义, 陷阵, 将驰, 巧说
        if prohibited:
            return False
        if cls.n_targets is None:
            return True
        for p in game.iterate_live_players():
            if cls.target_legal(player, p, cards):
                return True
        return False

    @classmethod
    def get_args(cls, player, cards):
        game = player.game
        event = Event(player, "modify_n_targets", card_type=cls, cards=cards)
        n_targets = game.trigger_skills(event, cls.n_targets)  # 方天画戟, 天义, 灭计, 疠火
        options = [p for p in game.iterate_live_players() if cls.target_legal(player, p, cards)]
        if n_targets is None:
            targets = options
        else:
            event = Event(player, "get_args", card_type=cls, cards=cards)
            targets = [options[i] for i in player.agent().choose_many(options, (1, n_targets), event, "请选择目标")]
        use_card_event = UseCardEvent(player, cls, cards, targets)
        event = Event(player, "confirm_targets", use_card_event)  # TODO: print use card message before 流离
        targets = game.trigger_skills(event, targets)  # 流离, 短兵, 求援, 巧说
        # sort targets according to resolution order of current turn
        sorted_targets = []
        for p in game.iterate_live_players():
            while p in targets:  # a target may be appointed multiple times
                targets.remove(p)
                sorted_targets.append(p)
        return sorted_targets

    @classmethod
    def effect(cls, player, cards, args):
        game = player.game
        use_card_event = UseCardEvent(player, cls, cards, args)
        game.trigger_skills(use_card_event)  # 雌雄双股剑, 集智, 激昂
        if game.trigger_skills(Event(player, "test_card_invalidate", use_card_event), False):
            return  # 设伏

    @classmethod
    def __str__(cls):
        return cls.__name__


class Skill:
    labels = set()

    def __init__(self, owner=None):
        self.owner = owner

    def can_use(self, player, event):
        return False

    def use(self, player, event, data=None):
        return data

    def __str__(self):
        return f"{type(self).__name__}"


class Character:
    def __init__(self, name, male=True, faction="?", hp=4, skills=None):
        self.name = name
        self.male = male
        self.faction = faction
        self.hp = hp
        self.skills = skills

    def __str__(self):
        gender = "♂" if self.male else "♀"
        return f"{self.name} {gender} {self.faction}"


class Player:
    next_id = 0

    def __init__(self, game, character=None):
        self.id = Player.next_id
        Player.next_id += 1
        self.game = game
        self.character = character
        if character:
            self.name = character.name
            self.male = character.male
            self.faction = character.faction
            self.hp_cap = character.hp
            self.skills = [skill(self) for skill in character.skills]
        else:
            self.name = f"玩家{self.id}"
            self.male = True
            self.faction = "?"
            self.hp_cap = 4
            self.skills = []
        self.hp = self.hp_cap
        self.hand = []
        self.装备区 = {}  # 武器, 防具, -1坐骑, +1坐骑
        self.判定区 = {}  # 闪电, 乐不思蜀, 兵粮寸断
        self.repo = []  # 不屈, 屯田, 权计, 七星
        self.show_repo = True
        self.marks = defaultdict(int)  # 武魂, 狂风, 大雾, 狂暴, 忍戒
        self.drunk = False
        self.chained = False
        self.flipped = False

    def __str__(self):
        return self.name

    def pid(self):
        return self.game.get_pid(self)

    def next(self):
        return self.game.players[self.game.next_pid(self.pid())]

    def is_alive(self):
        return self.pid() in self.game.alive

    def agent(self):
        return self.game.agents[self.pid()]

    def is_wounded(self):
        return self.hp < self.hp_cap

    def attack_range(self):
        if "武器" not in self.装备区:
            return 1
        return self.装备区["武器"].type.range

    def info(self):
        gender = "♂" if self.male else "♀"
        equipped = "|".join(str(self.装备区[key]) for key in ["武器", "防具", "-1坐骑", "+1坐骑"] if key in self.装备区)
        pending = "|".join(str(card) for card in self.判定区.values())
        ans = f"{self.name} {gender} {self.faction} {self.hp}/{self.hp_cap} ({len(self.hand)}) [{equipped}] <{pending}>"
        if self.repo:
            if self.show_repo:
                ans += f" (({'、'.join(str(card) for card in self.repo)}))"
            else:
                ans += f" (({len(self.repo)}))"
        if self.marks:
            for mark, n in self.marks.items():
                if n == 1:
                    ans += f" #{mark}"
                elif n > 1:
                    ans += f" #{mark}x{n}"
        if self.chained:
            ans += " 锁"
        if self.flipped:
            ans += " 翻"
        return ans

    def total_cards(self, zones="手装"):
        ans = 0
        if "手" in zones:
            ans += len(self.hand)
        if "装" in zones:
            ans += len(self.装备区)
        if "判" in zones:
            ans += len(self.判定区)
        return ans

    def remove_card(self, card):
        if card in self.hand:
            self.hand.remove(card)
        elif card in self.装备区.values():
            key = None
            for k, v in self.装备区.items():
                if v == card:
                    key = k
                    break
            del self.装备区[key]
        elif card in self.判定区.values():
            key = None
            for k, v in self.判定区.items():
                if v == card:
                    key = k
                    break
            del self.判定区[key]
        elif card in self.repo:
            self.repo.remove(card)
        else:
            raise CardHandleError(f"{card}不在{self}那里")

    def cards(self, zones="手装", suits=None, types=None, return_places=False):
        ans = []
        if "手" in zones:
            # ans.extend(self.hand)
            ans.extend([("手牌", card) for card in self.hand])
        if "装" in zones:
            # ans.extend(self.装备区.values())
            ans.extend([("装备区的牌", card) for card in self.装备区.values()])
        if "判" in zones:
            # ans.extend(self.判定区.values())
            ans.extend([("判定区的牌", card) for card in self.判定区.values()])
        if suits is not None:
            ans = [(place, card) for (place, card) in ans if card.suit in suits]
        if types is not None:
            ans = [(place, card) for (place, card) in ans if issubclass(card.type, types)]
        if not return_places:
            ans = [card for (place, card) in ans]
        return ans

    def discard_n_cards(self, n, event=None):
        """
        Discard n cards in hand or equipment zone. n can be a range.
        If player has less than n cards (given that n is an int), then discard all cards.
        Return actual number of cards discarded.

        :param n: int or (int, int) tuple
        :param event: an Event
        :return: actual number of cards discarded
        """
        options = self.cards(return_places=True)
        if type(n) == int and len(options) <= n:
            place_card_tuples = options[:]
        else:
            place_card_tuples = [options[i] for i in
                                 self.agent().choose_many(options, n, event=event, message="请选择要弃置的牌")]
        n_discarded = len(place_card_tuples)
        if n_discarded > 0:
            print(f"{self}弃置了{'、'.join(str(card) for _, card in place_card_tuples)}")
            for place, card in place_card_tuples:
                self.game.lose_card(self, card, place[0], "弃置", event)
                self.game.table.append(card)
        return n_discarded


class Agent:
    def __init__(self, player):
        self.player = player

    def choose(self, choices, event, message=""):
        if not choices:
            raise NoOptions("no options for context", event)
        return random.randrange(len(choices))

    def _get_range(self, k, n):
        if type(k) == int:
            k_min, k_max = k, k
        else:
            k_min, k_max = k[0], k[1]
        if n < k_min:
            raise NoOptions(f"At least {k_min} choices are needed but given only {n}")
        k_max = min(k_max, n)
        return k_min, k_max

    def choose_many(self, choices, k, event, message=""):
        n = len(choices)
        k_min, k_max = self._get_range(k, n)
        k = random.randint(k_min, k_max)
        return random.sample(range(n), k)


class HumanAgent(Agent):
    def choose_many(self, choices, k, event, message=""):
        k_min, k_max = self._get_range(k, len(choices))
        if k_min == 1 and len(choices) == 1:
            return [0]
        elif k_min == 0 and len(choices) == 0:
            return []
        if message:
            print(message)
        else:
            print(event)
        for i, choice in enumerate(choices):
            if type(choice) in (list, tuple):
                text = ' '.join(str(c) for c in choice)
            else:
                text = str(choice)
            print(i, '-', text)
        while True:
            n_str = str(k_min) if k_min == k_max else f"{k_min}~{k_max}"
            ans = input(f"请选择{n_str}项：")
            if ans == "p":  # print info of players
                for p in self.player.game.iterate_live_players():
                    print(p.info())
            elif ans == "h": # print cards in hand
                print(*self.player.hand, sep="、")
            else:
                try:
                    if ans == "all":
                        ans = list(range(len(choices)))
                    else:
                        ans = [int(a) for a in ans.split()]
                    assert k_min <= len(ans) <= k_max
                    ss = set(ans)
                    assert len(ans) == len(ss)  # Ensure no duplicates
                    if ss:
                        assert 0 <= min(ss) and max(ss) < len(choices)
                    return ans
                except (ValueError, AssertionError):
                    print("非法输入。请重新选择。")

    def choose(self, choices, event, message=""):
        return self.choose_many(choices, 1, event, message)[0]


def get_agent(name, player):
    if name == "human":
        return HumanAgent(player)
    else:
        return Agent(player)


class StopGame(Exception):
    pass


class EndTurn(Exception):
    pass


class NoOptions(Exception):
    pass


class CardHandleError(Exception):
    pass
