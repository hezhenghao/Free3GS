import random

import core
from core import Event
from cardtype import get_cardtype
from skill import get_skill

PHASES = ["判定阶段", "摸牌阶段", "出牌阶段", "弃牌阶段"]


def load_cards(pack="标准版"):
    deck = []
    for line in open(f"resources/cards-{pack}.txt", encoding="utf-8"):
        suit, rank, name = line.strip().split("\t")
        card = core.Card(suit, rank, name, get_cardtype(name))
        deck.append(card)
    return deck


def load_characters():
    characters = {}
    for line in open("resources/characters.txt", encoding="utf-8"):
        if line[0] == "#":
            continue
        code, name, faction, hp, gender, skills = line.strip().split("\t")
        if name in characters:
            raise KeyError(f"There are more than one characters with the name {name}")
        hp = int(hp)
        male = (gender == "男")
        skills = [get_skill(skill) for skill in skills.split("|") if skill[0] != "!"]
        skills = [sk for sk in skills if sk is not None]
        if skills:
            characters[name] = core.Character(name, male, faction, hp, skills)
    return characters


class Game:
    def __init__(self, character_agent_tuples, pack="标准版"):
        self.characters = load_characters()
        self.players, self.agents = [], []
        for character, agent in character_agent_tuples:
            if character == "RANDOM":
                character = random.choice(list(self.characters.keys()))
            player = core.Player(self, self.characters[character])
            self.players.append(player)
            self.agents.append(core.get_agent(agent, player))
        # TODO: find a better way to associate players with agents than with pid
        self.pack = load_cards(pack)
        self.deck = list(self.pack)
        self.discard_pile = []
        self.table = []
        self.current_pid = 0
        self.alive = set(range(len(self.players)))
        self.attack_quota = 1
        self.drink_quota = 1
        self.skipped = set()
        self.autocast = True
        self.end_turn = False

    def current_player(self):
        return self.players[self.current_pid]

    def get_pid(self, player):
        for i, p in enumerate(self.players):
            if p is player:
                return i
        raise ValueError(f"{player} is not in the game")

    def next_pid(self, pid):
        pid = (pid + 1) % len(self.players)
        while pid not in self.alive:
            pid = (pid + 1) % len(self.players)
        return pid

    def next_player(self, player):
        return self.players[self.next_pid(self.get_pid(player))]

    def iterate_live_players(self):
        visited = set()
        pid = self.current_pid
        if pid not in self.alive:
            pid = self.next_pid(pid)
        while pid not in visited:
            yield self.players[pid]
            visited.add(pid)
            pid = self.next_pid(pid)

    def game_over(self):
        return len(self.alive) <= 1

    def find_card(self, card):
        for place in ["table", "discard_pile", "deck"]:
            if card in getattr(self, place):
                return None, place
        for player in self.iterate_live_players():
            for place in ["hand", "repo"]:
                if card in getattr(player, place):
                    return player, place
            for place in ["装备区", "判定区"]:
                if card in getattr(player, place).values():
                    return player, place
        return None, None

    def check_pack_integrity(self):
        position = {}
        for player in self.iterate_live_players():
            for place in ["hand", "repo"]:
                for card in getattr(player, place):
                    pos_str = f"{player}'s {place}"
                    if card in position:
                        raise core.CardHandleError(f"{card} is found in {pos_str} and in {position[card]}")
                    position[card] = pos_str
            for place in ["装备区", "判定区"]:
                for card in getattr(player, place).values():
                    pos_str = f"{player}'s {place}"
                    if card in position:
                        raise core.CardHandleError(f"{card} is found in {pos_str} and in {position[card]}")
                    position[card] = pos_str
        for place in ["table", "discard_pile", "deck"]:
            for card in getattr(self, place):
                if card in position:
                    raise core.CardHandleError(f"{card} is found in the {place} and in {position[card]}")
                position[card] = place
        for card in self.pack:
            if card not in position:
                raise core.CardHandleError(f"{card} is missing")

    def trigger_skills(self, event, data=None):
        for player in self.iterate_live_players():
            for skill_owner in self.iterate_live_players():
                for skill in skill_owner.skills:
                    if skill.can_use(player, event):  # skill owner is not necessarily skill user (颂威, 暴虐)
                        data = skill.use(player, event, data)
            for key in ["武器", "防具"]:
                if key not in player.装备区:
                    continue
                for skill in player.装备区[key].type.skills:
                    if skill.can_use(player, event):
                        data = skill.use(player, event, data)
        return data

    def distance(self, player1, player2):
        if player1 is player2:
            return 0
        if not player1.is_alive() or not player2.is_alive():
            return float("inf")
        n = 0
        player = player1
        while player is not player2:
            player = player.next()
            n += 1
        n = min(n, len(self.alive) - n)
        if "-1坐骑" in player1.装备区:
            n -= 1
        if "+1坐骑" in player2.装备区:
            n += 1
        n = self.trigger_skills(Event(player1, "calc_distance", to=player2), n)  # 马术, 飞影, 屯田, 义从
        if n < 1:
            n = 1
        return n

    def max_hand(self, player):
        n = player.hp
        n = self.trigger_skills(Event(player, "calc_max_hand"), n)  # 血裔, 权计, 宗室
        n = max(0, n)  # Avoid negative max_hand (e.g. from 横江)
        return n

    def draw_from_deck(self):
        if not self.deck:
            if not self.discard_pile:  # 平局
                raise core.StopGame
            random.shuffle(self.discard_pile)
            self.deck = self.discard_pile
            self.discard_pile = []
        card = self.deck.pop()
        return card

    def move_card(self, card, from_, to, cause=None):
        ...

    def deal_cards(self, player, n):
        if n <= 0:
            return
        cards = [self.draw_from_deck() for _ in range(n)]
        player.hand.extend(cards)
        print(f"{player}从牌堆里摸了{n}张牌")

    def lose_card(self, player, card, zone="手", type="弃置", cause=None):
        # self.trigger_skills(core.LoseCardEvent(player, card, zone, type, cause=cause))
        player.remove_card(card)
        self.trigger_skills(core.LoseCardEvent(player, card, zone, type, cause=cause))

    def discard(self, cards):
        # cards = self.trigger_skills(core.Event)
        self.discard_pile.extend(cards)
        # TODO: trigger skills 固政, 巨象, 琴音, 忍戒, 礼让, 落英, 旋风, 纵玄, 明哲

    def discard_all_cards(self, player, zones="手装判", cause=None):
        long_name = {"手": "手牌", "装": "装备区的牌", "判": "判定区的牌"}
        for zone in "手装判":
            if zone not in zones:
                continue
            to_discard = player.cards(zone)
            if not to_discard:
                continue
            for card in to_discard:
                self.lose_card(player, card, zone, "弃置", cause=cause)
            self.table.extend(to_discard)
            print(f"{player}的{long_name[zone]}{'、'.join(str(card) for card in to_discard)}被弃置")

    def kill_player(self, player, cause=None):
        self.alive.discard(player.pid())
        print(f"{player}阵亡。仍存活玩家：" + "、".join(str(p) for p in self.iterate_live_players()))
        if self.game_over():
            raise core.StopGame
        event = Event(player, "die", cause)
        self.trigger_skills(event)  # 行殇
        self.discard_all_cards(player, "手装判", event)
        if player.repo:
            print(f"{player}武将牌上的牌{'、'.join(str(card) for card in player.repo)}被弃置")
            self.table.extend(player.repo)
            player.repo = []
        if cause.what == "damage" and cause.who is not None:
            self.reward_or_punish(cause.who, player)
        # Use skills of the dead: 断肠, 武魂, 挥泪, 追忆
        for skill in player.skills:
            if skill.can_use(player, event):
                skill.use(player, event)
        if player is self.current_player():
            self.end_turn = True  # Use flag instead of exception to avoid incomplete events.
                                  # e.g.: 1血典韦发动强袭死亡后，由于结算终止，无法造成伤害

    def reward_or_punish(self, player, killed):
        if not player.is_alive():
            return
        self.deal_cards(player, 3)

    def recover(self, player, n, cause=None):
        n = self.trigger_skills(Event(player, "recover", cause), n)  # 救援, 淑慎
        n = min(n, player.hp_cap - player.hp)
        if n > 0:
            player.hp += n
            print(f"{player}回复了{n}点体力，体力值为{player.hp}")

    def lose_health(self, player, n, cause=None):
        player.hp -= n
        print(f"{player}的体力值变为{player.hp}")
        self.trigger_skills(Event(player, "lose_health", cause))  # 伤逝
        if player.hp <= 0:
            print(f"{player}进入濒死状态")
            event = Event(player, "dying", cause)
            self.trigger_skills(event)  # 不屈, 涅槃
            if self.try_to_save(player, event):
                self.trigger_skills(Event(player, "saved"))  # 绝境
                return
            self.kill_player(player, cause)

    def damage(self, player, n, inflicter=None, cause=None, damage_type=None):
        """
        Damage player with a damage value of n

        :param player: Player to be damaged
        :param n: Damage value
        :param inflicter: Inflicter of the damage
        :param cause: Event that cause the damage
        :param damage_type: Type of the damage. Can be None, "火" or "雷"
        :return:
        """
        if n <= 0:
            return
        inflicter = self.trigger_skills(Event(player, "modify_damage_inflicter", cause), inflicter)
        event = core.DamageEvent(inflicter, player, n, cause, damage_type)
        n = self.trigger_skills(Event(inflicter, "造成伤害时", event), n)  # 裸衣, 寒冰剑, 麒麟弓, 古锭刀
        if n <= 0:
            return
        n = self.trigger_skills(Event(player, "受到伤害时", event), n)  # 天香, 藤甲, 白银狮子
        if n <= 0:
            return
        event.n = n
        str_inflicter = f"{inflicter}造成的" if inflicter is not None else ""
        str_type = f"{damage_type}属性" if damage_type is not None else ""
        print(f"{player}受到了{str_inflicter}{n}点{str_type}伤害")
        # TODO: Find a better way to modify damage value
        self.lose_health(player, n, event)
        self.trigger_skills(Event(inflicter, "造成伤害后", event))  # 狂骨, 烈刃, 暴虐, 忘隙
        if player.is_alive():
            self.trigger_skills(Event(player, "受到伤害后", event))  # 奸雄, 反馈, 刚烈, 遗计, 节命, 放逐, 忘隙, 智愚, 新生, 悲歌
        if not damage_type or not player.chained:
            return
        self.chain(player, event)
        if cause and cause.what != "chain_transfer":
            transfer_event = Event(player, "chain_transfer", event)
            for p in self.iterate_live_players():
                if p.chained:
                    self.damage(p, n, inflicter, transfer_event, damage_type)

    def change_hp_cap(self, player, diff, cause=None):
        print(f"{player}的体力上限变为{player.hp_cap + diff}")
        player.hp_cap += diff
        if player.hp > player.hp_cap:
            n = player.hp - player.hp_cap
            self.lose_health(player, n, cause)
        self.trigger_skills(Event(player, "change_hp_cap", cause))

    def flip(self, player, cause=None):
        if not player.flipped:
            print(f"{player}将武将牌翻至背面")
        else:
            print(f"{player}将武将牌翻回正面")
        player.flipped = not player.flipped
        self.trigger_skills(Event(player, "flip", cause))

    def chain(self, player, cause=None):
        if not player.chained:
            print(f"{player}被绑上了铁索")
        else:
            print(f"{player}身上的铁索被解开了")
        player.chained = not player.chained
        self.trigger_skills(Event(player, "chain", cause))

    def change_mark(self, player, mark, diff, cause=None):
        if diff > 0:
            print(f"{player}获得了{diff}个{mark}标记")
        elif diff < 0:
            if mark not in player.marks or player.marks[mark] < -diff:
                raise ValueError(f"{player}想要弃置{-diff}个{mark}标记，但标记数量不足")
            print(f"{player}失去了{-diff}个{mark}标记")
        player.marks[mark] += diff

    def can_attack(self, player1, player2):
        return player1 is not player2 and self.distance(player1, player2) <= player1.attack_range()

    def pick_card(self, player, target, zones="手装", event=None, message="请选择"):
        """
        Let player pick one card from target

        :param player: The player who chooses the card
        :param target: The player whose card is to be picked
        :param zones: Zones to pick the card from. A string containing any number of the characters "手", "装" and "判"
        :param event: The Event that triggered this pick
        :param message: Prompt shown to the player (if he is human)
        :return: A (place, card) tuple, or (None, None) if there is nothing to choose from
        """
        options = []
        if "手" in zones and target.hand:
            options.append(("手牌", f"({len(target.hand)})"))
        for zone in "装判":
            if zone in zones:
                options.extend(target.cards(zone, return_places=True))
        if not options:
            return None, None
        place, card = options[player.agent().choose(options, event, message)]
        if place == "手牌":
            card = random.choice(target.hand)
        return place, card

    def elicit_action(self, player, event, message):
        choices = [["pass"]]
        for card in player.hand:
            if event.who is player and event.what == "play":
                can_use = card.type.can_use(player, [card])
                if card.type.can_recast:
                    choices.append(["重铸", card])
            elif event.who is player and event.what == "card_asked":
                can_use = issubclass(card.type, event.args["card_type"])
                if can_use:
                    can_use = self.trigger_skills(Event(player, "test_respond_prohibited", event, card=card), can_use)
            else:
                can_use = False
            if can_use:
                choices.append(["使用", card])
        for skill_owner in self.iterate_live_players():  # skill owner is not necessarily skill user (黄天, 制霸)
            for skill in skill_owner.skills:
                if skill.can_use(player, event):
                    choices.append(["发动", skill])
        for equip in player.装备区.values():
            for skill in equip.type.skills:
                if skill.can_use(player, event):
                    choices.append(["发动", skill])
        choice = choices[player.agent().choose(choices, event, message)]
        return choice

    def use_card(self, player, card):  # used during play, not during trigger events or response
        try:
            args = card.type.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要使用{card}，但中途取消")
            return
        str_targets = ""
        if args:
            str_targets = "对" + '、'.join(str(target) for target in args)
        print(f"{player}{str_targets}使用了{card}")
        event = core.UseCardEvent(player, card.type, [card], args)
        self.lose_card(player, card, "手", "使用", cause=Event(player, "use_card_cost", event))
        self.table.append(card)
        card.type.effect(player, [card], args)

    def use_skill(self, player, skill):  # used during play, not during trigger events or response
        try:
            skill.use(player, Event(player, "play"))
        except core.NoOptions:
            print(f"{player}想要发动技能{skill},但中途取消")

    def ask_for_response(self, player, card_type, event, message, verb="打出"):
        ask_event = Event(player, "card_asked", card_type=card_type, cause=event, verb=verb)
        if self.trigger_skills(Event(player, "test_respond_disabled", ask_event), False):
            return None, []
        ctype, cards = self.trigger_skills(Event(player, "pre_card_asked", ask_event), (False, []))  # 八卦阵, 激将, 护驾, 傲才
        if not ctype:
            response = self.elicit_action(player, ask_event, message)
            if response[0] == "使用":
                card = response[1]
                print(f"{player}{verb}了{card}")
                self.lose_card(player, card, "手", verb, cause=ask_event)
                self.table.append(card)
                ctype, cards = card.type, [card]
            elif response[0] == "发动":
                skill = response[1]
                ctype, cards = skill.use(player, ask_event, (None, []))
        if ctype:
            self.trigger_skills(Event(player, "respond", event, card_type=card_type, cards=cards))
        #TODO: Responding to 借刀杀人 or 青龙偃月刀特效 with a 杀 is counted both as a 打出 and as a 使用,
        # resulting in double counting for 蒺藜
        return ctype, cards

    def try_to_save(self, player, cause=None):
        for savior in self.iterate_live_players():
            while player.hp <= 0:
                card_type = get_cardtype("桃")
                ctype, cards = self.ask_for_response(savior, card_type, cause,
                                                     f"{player}即将阵亡，求{1 - player.hp}个桃", "使用")
                if ctype:
                    use_card_event = core.UseCardEvent(savior, ctype, cards, [player], cause)
                    self.recover(player, 1, use_card_event)
                else:
                    if player is not savior:
                        break
                    card_type = get_cardtype("酒")
                    ctype, cards = self.ask_for_response(savior, card_type, cause,
                                                         f"{player}（你）即将阵亡，请使用酒", "使用")
                    if ctype:
                        use_card_event = core.UseCardEvent(savior, ctype, cards, [player], cause)
                        self.recover(player, 1, use_card_event)
                    else:
                        break
            else:  # executed when not breaked
                return True
        return False

    def ask_for_nullification(self, event: core.UseCardEvent, target):
        card_name = event.card_type.__name__
        if target is not None:
            message = f"{card_name}即将对玩家{target}生效，询问无懈可击"
        else:
            message = f"{card_name}即将生效，询问无懈可击"  # when use 无懈可击 against 无懈可击
        card_type = get_cardtype("无懈可击")
        nullified = False
        for player in self.iterate_live_players():
            nullified, resp_cards = self.ask_for_response(player, card_type, event, message, "打出")
            if nullified:
                resp_event = core.UseCardEvent(player, card_type, resp_cards, None, event)
                nullified = not self.ask_for_nullification(resp_event, None)
                break
        return nullified

    def judge(self, player, cause):
        judge_event = Event(player, "judge", cause)
        judgment = self.draw_from_deck()
        if cause.what == "use_card":
            reason = cause.card_type.__name__
        else:
            reason = type(cause.skill).__name__
        print(f"{player}的{reason}判定牌为{judgment}")
        # TODO: better design for judgments in skills: 刚烈, 洛神, 颂威, 屯田, 铁骑, 暴虐, 悲歌
        judgment = self.trigger_skills(judge_event, judgment)  # 鬼才, 鬼道
        # TODO: 红颜
        self.table.append(judgment)
        self.trigger_skills(Event(player, "judged", cause, result=judgment))  # 天妒, 颂威
        return judgment

    def 拼点(self, player1, player2, cause):
        event = Event(player1, "拼点", cause, other=player2)
        print(f"{player1}对{player2}发起拼点")
        cards = []
        for p in [player1, player2]:
            card = p.hand[p.agent().choose(p.hand, event, "请选择拼点的牌")]
            self.lose_card(p, card, "手", "拼点", cause=event)
            cards.append(card)
        if cards[0].rank_value() > cards[1].rank_value():
            winner = player1
        else:
            winner = player2
        win_str = "赢" if winner is player1 else "没赢"
        print(f"{player1}拼点的牌是{cards[0]}，{player2}拼点的牌是{cards[1]}，{player1}{win_str}")
        self.table.extend(cards)
        self.trigger_skills(Event(player1, "拼点后", cause, whom=player2, result=(winner, cards[0], cards[1])))
        return winner, cards[0], cards[1]

    def view_cards(self, player, cards, cause):
        options = ["OK"] + cards
        player.agent().choose(options, cause, "选择任意选项结束观看")

    def 判定阶段(self):
        player = self.current_player()
        while player.判定区:
            card_name, card = player.判定区.popitem()
            self.table.append(card)
            card_type = get_cardtype(card_name)
            event = core.UseCardEvent(None, card_type, [card], [player])
            if self.ask_for_nullification(event, player):
                card_type.miss_effect(card, self)
                continue
            judgment = self.judge(player, event)
            if card_type.hit(judgment):
                card_type.hit_effect(card, self)
            else:
                card_type.miss_effect(card, self)

    def 摸牌阶段(self):
        player = self.current_player()
        event = Event(player, "摸牌阶段")
        n = self.trigger_skills(event, 2)
        self.deal_cards(player, n)

    def 出牌阶段(self):
        player = self.current_player()
        event = Event(player, "play")
        while not self.end_turn:
            action = self.elicit_action(player, event, "请选择下一步的行动")
            if action[0] == "pass":
                break
            try:
                # getattr(self, action[0])(player, action[1])
                if action[0] == "使用":
                    self.use_card(player, action[1])
                elif action[0] == "重铸":
                    card = action[1]
                    print(f"{player}重铸了手牌{card}")
                    self.lose_card(player, card, "手", "重铸", event)
                    self.table.append(card)
                    self.deal_cards(player, 1)
                elif action[0] == "发动":
                    self.use_skill(player, action[1])
                else:
                    raise ValueError(f"Unknown action {action}")
            except core.NoOptions:
                pass
            self.discard(self.table)
            self.table = []

    def 弃牌阶段(self):
        player = self.current_player()
        n = max(0, len(player.hand) - self.max_hand(player))
        event = Event(player, "弃牌阶段")
        to_discard = []
        if n > 0:
            to_discard = [player.hand[i] for i in player.agent().choose_many(player.hand, n, event, "请选择弃置的牌")]
            print(f"{player}弃置了" + "、".join([str(card) for card in to_discard]))
            for card in to_discard:
                self.lose_card(player, card, "手", "弃置", cause=event)
        to_discard = self.trigger_skills(event, to_discard)  # 固政, 琴音, 忍戒
        self.discard(to_discard)

    def exec_phase(self, phase):
        getattr(self, phase)()

    def run_turn(self):
        self.discard(self.table)
        self.table = []
        self.check_pack_integrity()
        self.attack_quota = 1
        self.drink_quota = 1
        self.skipped.clear()
        self.end_turn = False
        for p in self.iterate_live_players():
            p.drunk = False
        player = self.current_player()
        try:
            print(f"============ 牌堆数：{len(self.deck)}")
            print(f"{self.get_pid(player) + 1}号位{player}的回合开始了")
            print(player.info())
            if player.flipped:
                self.flip(player)
            else:
                self.trigger_skills(Event(player, "before_turn_start"))  # 化身, 志继, 若愚, 凿险, 魂姿, 自立
                self.trigger_skills(Event(player, "turn_start"))  # 观星, 洛神
                for phase in PHASES:
                    if self.end_turn:
                        break  # Avoid problems such as characters killed by 闪电
                    self.trigger_skills(Event(player, "test_skip_phase", phase=phase))  # 克己, 神速, 巧变, 放权
                    if phase not in self.skipped:
                        self.trigger_skills(Event(player, "phase_start", phase=phase))
                        self.exec_phase(phase)
                        self.trigger_skills(Event(player, "phase_end", phase=phase))
                    else:
                        print(f"跳过{phase}")
                self.trigger_skills(Event(player, "turn_end"))  # 闭月, 据守, 放权
                self.trigger_skills(Event(player, "after_turn_end"))  # 化身, 连破
            if player.is_alive():
                print(player.info())
        except core.EndTurn:
            return

    def run(self):
        random.shuffle(self.deck)
        for player in self.players:
            self.deal_cards(player, 4)
        self.trigger_skills(Event(None, "game_start"))  # 化身, 七星
        self.current_pid = 0
        try:
            while True:
                self.run_turn()
                self.current_pid = self.next_pid(self.current_pid)
        except core.StopGame:
            print("游戏结束。胜利者是：" + '、'.join(str(p) for p in self.iterate_live_players()))
