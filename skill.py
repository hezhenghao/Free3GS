import core
import random

from core import Skill, Event, UseSkillEvent
from cardtype import get_cardtype as C_


## ======= 标准版 =======
# ======= 蜀 =======

class 仁德(Skill):
    """
    出牌阶段，你可以将任意张手牌交给其他角色，每回合你以此法给出第二张牌时，回复1点体力。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_count = 0

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and player.hand

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_count = 0
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        card = player.hand[player.agent().choose(player.hand, cost_event, "请选择一张手牌交给其他角色")]
        players = [p for p in game.iterate_live_players() if p is not player]
        target = players[player.agent().choose(players, use_skill_event, "请选择要将牌交给的角色")]
        game.lose_card(player, card, "手", "获得", cost_event)
        target.hand.append(card)
        print(f"{player}发动技能{self}，将一张手牌交给了{target}")
        self.use_count += 1
        if self.use_count == 2:
            game.recover(player, 1, use_skill_event)


class 激将(Skill):
    """
    主公技，当你需要使用或打出一张【杀】时，你可以令其他蜀势力角色打出一张【杀】（视为由你使用或打出）。
    """
    labels = {"主公技"}

    def _get_response(self, player, event):
        game = player.game
        for p in game.iterate_live_players():
            if p is player or p.faction != "蜀":
                continue
            ctype, cards = game.ask_for_response(p, C_("杀"), event, f"请选择是否响应{player}的技能{self}出杀")
            if ctype:
                print(f"{p}响应{player}的技能{self}打出了{ctype.__name__}")
                return ctype, cards
        return None, []

    def can_use(self, player, event):  # pre_card_asked(player) <- card_asked(player, 闪)
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "play" and C_("杀").can_use(player, []) or
                event.what == "pre_card_asked" and issubclass(C_("杀"), event.cause.args["card_type"]))

    def use(self, player, event, data=None):
        if event.what == "pre_card_asked":
            ctype, cards = data
            if ctype:
                return data
            use_skill_event = UseSkillEvent(player, self, None, event)
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}，请求蜀国角色为其出杀")
                return self._get_response(player, use_skill_event)
            return None, []
        # event.what == "play"
        try:
            targets = C_("杀").get_args(player, [])
        except core.NoOptions:
            print(f"{player}想要使用杀，但中途取消")
            return
        print(f"{player}发动了技能{self}，请求蜀国角色为其对{'、'.join(str(p) for p in targets)}出杀")
        use_skill_event = UseSkillEvent(player, self, targets, event)
        ctype, cards = self._get_response(player, use_skill_event)
        if ctype:
            ctype.effect(player, cards, targets)


class 武圣(Skill):
    """
    你可以将一张红色牌当【杀】使用或打出。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player and player.cards(suits="♥♦")):
            return False
        return (event.what == "play" and C_("杀").can_use(player, []) or
                event.what == "card_asked" and issubclass(C_("杀"), event.args["card_type"]))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(suits="♥♦", return_places=True)
        ctype = C_("杀")
        place, card = options[player.agent().choose(options, cost_event, "请选择一张红色牌")]
        zone = place[0]
        if event.what == "card_asked":
            game.lose_card(player, card, zone, "打出", cost_event)
            game.table.append(card)
            print(f"{player}发动了技能{self}，将{card}当杀打出")
            return ctype, [card]
        # event.what == "play"
        key = None
        if zone == "装":
            for k, val in player.装备区.items():
                if val is card:
                    key = k
                    break
        player.remove_card(card)  # remove_card before get_args to avoid cases when using the card for 武圣 will make
        # the attack invalid (e.g. target becomes out of range, player no longer has attack quota (诸葛连弩), or the
        # number of targets is changed (方天画戟))
        try:
            if not ctype.can_use(player, [card]):
                raise core.NoOptions
            args = ctype.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要使用杀，但中途取消")
            if zone == "手":
                player.hand.append(card)
            else:
                player.装备区[key] = card
            return
        if zone == "手":
            player.hand.append(card)
        else:
            player.装备区[key] = card
        game.lose_card(player, card, zone, "使用", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当杀对{'、'.join(str(target) for target in args)}使用")
        ctype.effect(player, [card], args)


class 义绝(Skill):
    """
    出牌阶段限一次，你可以与一名其他角色拼点：
    若你赢，则直到回合结束，每当你对其造成伤害时，伤害+1；
    若你没赢，则直到回合结束，防止你对其造成的一切伤害。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = None
        self.target = None

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p is not player and p.hand]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "play":
            return self.buff is None and len(player.hand) > 0 and self.legal_targets(player)
        elif event.what == "造成伤害时":  # 造成伤害时 <- damage
            return self.buff is not None and event.cause.whom is self.target
        elif event.what == "turn_end":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "造成伤害时":
            if self.buff == "good":
                print(f"{player}的技能{self}被触发，伤害+1")
                return data + 1
            else:
                print(f"{player}的技能{self}被触发，防止伤害")
                return 0
        elif event.what == "turn_end":
            self.buff = None
            self.target = None
            return
        # event.what == "play"
        use_skill_event = UseSkillEvent(player, self)
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}对{target}发动了技能{self}")
        self.target = target
        use_skill_event.targets = [target]
        winner, _, _ = game.拼点(player, target, use_skill_event)
        if winner is player:
            self.buff = "good"
        else:
            self.buff = "bad"


class 咆哮(Skill):
    """
    锁定技，你使用【杀】无次数限制。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "test_attack_quota":
            return True
        return event.what == "use_card" and issubclass(event.card_type, C_("杀"))

    def use(self, player, event, data=None):
        if event.what == "test_attack_quota":
            return True
        # event.what == "use_card
        game = player.game
        if game.attack_quota <= 0 and player is game.current_player():
            print(f"{player}发动了{self}，额外出杀")


class 观星(Skill):
    """
    准备阶段，你可以观看牌堆顶的X张牌（X为全场角色数且最多为5），然后将这些牌以任意顺序放置于牌堆顶或牌堆底。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_start"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not game.autocast and not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        n = min(len(game.alive), 5)
        print(f"{player}发动了技能{self}，观看了牌堆顶的{n}张牌")
        cards = [game.draw_from_deck() for _ in range(n)]
        top_cards = [cards[i] for i in
                     player.agent().choose_many(cards, (0, n), use_skill_event, "请选择并排列放置于牌堆顶的牌")]
        for card in top_cards:
            cards.remove(card)
        if cards:
            cards = [cards[i] for i in
                     player.agent().choose_many(cards, len(cards), use_skill_event, "请排列放置于牌堆底的牌")]
        game.deck = cards[::-1] + game.deck + top_cards[::-1]
        print(f"{player}将{len(top_cards)}张牌放回了牌堆顶，将{len(cards)}张牌放回了牌堆底")


class 空城(Skill):
    """
    锁定技，若你没有手牌，你不能成为【杀】或【决斗】的目标。
    """

    def can_use(self, player, event):  # test_target_prohibited <- use_card
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "test_target_prohibited":
            return issubclass(event.cause.card_type, (C_("杀"), C_("决斗"))) and not player.hand
        elif event.what == "lose_card":
            return event.zone == "手" and not player.hand
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "test_target_prohibited":
            return True
        else:  # event.what == "lose_card:
            print(f"{player}的技能{self}被触发，不能成为杀或决斗的目标")


class 龙胆v1(Skill):
    """
    你可以将【杀】当【闪】、【闪】当【杀】使用或打出。
    """

    def can_use(self, player, event):
        if player is not self.owner or event.who is not player:
            return False
        if event.what == "play" and C_("杀").can_use(player, []) and player.cards(types=C_("闪")):
            return True
        if event.what != "card_asked":
            return False
        return (issubclass(C_("杀"), event.args["card_type"]) and player.cards(types=C_("闪")) or
                issubclass(C_("闪"), event.args["card_type"]) and player.cards(types=C_("杀")))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        if event.what == "play":
            options = player.cards(types=C_("闪"))
            card = options[player.agent().choose(options, cost_event, "请选择")]
            try:
                args = C_("杀").get_args(player, [card])
            except core.NoOptions:
                print(f"{player}想要使用杀，但中途取消")
                return
            game.lose_card(player, card, "手", "使用", cost_event)
            game.table.append(card)
            print(f"{player}发动了技能{self}，将{card}当杀对{'、'.join(str(target) for target in args)}使用")
            C_("杀").effect(player, [card], args)
            return
        # event.what == "card_asked"
        if issubclass(C_("杀"), event.args["card_type"]):
            asked, used = "杀", "闪"
        else:
            asked, used = "闪", "杀"
        options = player.cards(types=C_(used))
        card = options[player.agent().choose(options, cost_event, "请选择")]
        game.lose_card(player, card, "手", "打出", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当{asked}打出")
        return C_(asked), [card]

    def __str__(self):
        return "龙胆"


class 龙胆v2(Skill):
    """
    你可以将【杀】当【闪】、【闪】当【杀】使用或打出。若你在你的回合外这样做，你可以摸一张牌。
    """

    def can_use(self, player, event):
        if player is not self.owner or event.who is not player:
            return False
        if event.what == "play" and C_("杀").can_use(player, []) and player.cards(types=C_("闪")):
            return True
        if event.what != "card_asked":
            return False
        return (issubclass(C_("杀"), event.args["card_type"]) and player.cards(types=C_("闪")) or
                issubclass(C_("闪"), event.args["card_type"]) and player.cards(types=C_("杀")))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        if event.what == "play":
            options = player.cards(types=C_("闪"))
            card = options[player.agent().choose(options, cost_event, "请选择")]
            try:
                args = C_("杀").get_args(player, [card])
            except core.NoOptions:
                print(f"{player}想要使用杀，但中途取消")
                return
            game.lose_card(player, card, "手", "使用", cost_event)
            game.table.append(card)
            print(f"{player}发动了技能{self}，将{card}当杀对{'、'.join(str(target) for target in args)}使用")
            if game.current_player() is not player:
                game.deal_cards(player, 1)
            C_("杀").effect(player, [card], args)
            return
        # event.what == "card_asked"
        if issubclass(C_("杀"), event.args["card_type"]):
            asked, used = "杀", "闪"
        else:
            asked, used = "闪", "杀"
        options = player.cards(types=C_(used))
        card = options[player.agent().choose(options, cost_event, "请选择")]
        game.lose_card(player, card, "手", "打出", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当{asked}打出")
        if game.current_player() is not player:
            game.deal_cards(player, 1)
        return C_(asked), [card]

    def __str__(self):
        return "龙胆"


龙胆 = 龙胆v2


class 马术(Skill):
    """
    锁定技，你计算与其他角色的距离-1。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "calc_distance"

    def use(self, player, event, data=None):
        return data - 1


class 铁骑(Skill):
    """
    当你使用【杀】指定一个目标后，你可以进行判定，若结果为红色，该角色不能使用【闪】响应此【杀】。
    """

    def can_use(self, player, event):  # test_respond_disabled <- card_asked <- use_card
        if not (player is self.owner and event.what == "test_respond_disabled"):
            return False
        event0 = event.cause.cause
        return event0.who is player and event0.what == "use_card" and issubclass(event0.card_type, C_("杀"))

    def use(self, player, event, data=None):
        if data:
            return True
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [event.who], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            judgment = game.judge(player, use_skill_event)
            if judgment.suit in "♥♦":
                return True
        return False


class 集智(Skill):
    """
    当你使用普通锦囊牌时，你可以摸一张牌。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        elif event.what == "use_card":
            return issubclass(event.card_type, C_("即时锦囊"))
        elif event.what == "respond":
            return issubclass(event.args["card_type"], C_("即时锦囊"))
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            player.game.deal_cards(player, 1)


class 奇才(Skill):
    """
    锁定技，你使用锦囊牌无距离限制。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "modify_use_range" \
               and issubclass(event.args["card_type"], C_("锦囊牌"))

    def use(self, player, event, data=None):
        return None


# ======= 魏 =======

class 奸雄(Skill):
    """
    当你受到伤害后，你可以获得造成伤害的牌。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage <- use_card
        if not (player is self.owner and event.who is player and event.what == "受到伤害后"):
            return False
        event0 = event.cause.cause
        return event0.what == "use_card" and event0.cards

    def use(self, player, event, data=None):
        game = player.game
        cards = event.cause.cause.cards
        use_skill_event = UseSkillEvent(player, self, [], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            cards_acquired = []
            for card in cards:
                if card in game.table:
                    game.table.remove(card)
                    player.hand.append(card)
                    cards_acquired.append(card)
            print(f"{player}发动了技能{self}，获得了{'、'.join(str(card) for card in cards_acquired)}")


class 护驾(Skill):
    """
    主公技，你可以令其他魏势力角色选择是否替你使用或打出【闪】。
    """
    labels = {"主公技"}

    def can_use(self, player, event):  # pre_card_asked(player) <- card_asked(player, 闪)
        return (player is self.owner and event.who is player and event.what == "pre_card_asked"
                and issubclass(C_("闪"), event.cause.args["card_type"]))

    def use(self, player, event, data=None):
        ctype, cards = data
        if ctype:
            return data
        game = player.game
        use_skill_event = UseSkillEvent(player, self, None, event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}，请求魏国角色为其出闪")
            for p in game.iterate_live_players():
                if p is player or p.faction != "魏":
                    continue
                if not p.agent().choose(["不响应", "响应"], use_skill_event, f"请选择是否响应{player}的技能{self}出闪"):
                    continue  # This is to avoid compulsary using of 八卦阵 under autocast
                ctype, cards = game.ask_for_response(p, C_("闪"), use_skill_event, f"请选择是否响应{player}的技能{self}出闪")
                if ctype:
                    print(f"{p}响应{player}的技能{self}打出了闪（{'、'.join(str(c) for c in cards)}）")
                    return ctype, cards
        return None, []


class 反馈(Skill):
    """
    当你受到伤害后，你可以获得伤害来源的一张牌。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        if not (player is self.owner and event.who is player and event.what == "受到伤害后"):
            return False
        inflicter = event.cause.who
        return inflicter is not None and inflicter.cards()

    def use(self, player, event, data=None):
        game = player.game
        inflicter = event.cause.who
        use_skill_event = UseSkillEvent(player, self, [inflicter], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            place, card = game.pick_card(player, inflicter, "手装", use_skill_event,
                                         f"请选择发动技能{self}要获得的{inflicter}的牌")
            if place[0] == "手":
                print(f"{player}获得了{inflicter}的一张手牌")
            else:
                print(f"{player}获得了{inflicter}的{place}{card}")
            game.lose_card(inflicter, card, place[0], "获得", use_skill_event)
            player.hand.append(card)


class 鬼才(Skill):
    """
    一名角色的判定牌生效前，你可以打出一张手牌代替之。
    """

    def can_use(self, player, event):
        return player is self.owner and event.what == "judge" and player.hand

    def use(self, player, event, data=None):
        game = player.game
        judgment = data
        use_skill_event = UseSkillEvent(player, self, cause=event)
        options = ["pass"] + player.cards("手")
        choice = player.agent().choose(options, use_skill_event, f"请选择是否发动技能{self}")
        if choice:
            card = options[choice]
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            game.lose_card(player, card, "手", "打出", cost_event)
            game.table.append(judgment)  # Game.judge will add judge result to the table
            print(f"{player}发动了技能{self}，将判定牌改为{card}")
            return card
        else:
            return judgment


class 刚烈(Skill):
    """
    当你受到伤害后，你可以进行判定，若结果不为♥，则伤害来源选择一项：
    1. 弃置两张手牌；
    2. 受到你造成的1点伤害。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        if not (player is self.owner and event.who is player and event.what == "受到伤害后"):
            return False
        inflicter = event.cause.who
        return inflicter is not None and inflicter.is_alive()

    def use(self, player, event, data=None):
        game = player.game
        inflicter = event.cause.who
        use_skill_event = UseSkillEvent(player, self, [inflicter], event)
        if not (game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}")):
            return
        print(f"{player}发动了技能{self}")
        judgment = game.judge(player, use_skill_event)
        if judgment.suit == "♥":
            print(f"{player}的技能{self}发动失败")
            return
        print(f"{player}的技能{self}生效，令{inflicter}弃置两张手牌或受到1点由他造成的伤害")
        if len(inflicter.hand) >= 2:
            if inflicter.agent().choose([f"受到{player}对你造成的1点伤害", "弃置两张手牌"], use_skill_event, "请选择"):
                options = inflicter.hand
                cards = [options[i] for i in inflicter.agent().choose_many(options, 2, use_skill_event, "请选择弃置的手牌")]
                for card in cards:
                    game.lose_card(inflicter, card, "手", "弃置", use_skill_event)
                game.table.extend(cards)
                print(f"{inflicter}弃置了手牌{cards[0]}、{cards[1]}")
                return
        game.damage(inflicter, 1, player, use_skill_event)


class 突袭v1(Skill):
    """
    摸牌阶段，你可以放弃摸牌，改为获得最多两名其他角色的各一张手牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "摸牌阶段"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        options = [p for p in game.iterate_live_players() if p is not player and p.hand]
        if not options or not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        targets = [options[i] for i in player.agent().choose_many(options, (1, 2), use_skill_event, f"请选择目标角色")]
        print(f"{player}发动了技能{self}，从{'、'.join(str(t) for t in targets)}那里获得了一张手牌")
        for target in targets:
            card = random.choice(target.hand)
            game.lose_card(target, card, "手", "获得", use_skill_event)
            player.hand.append(card)
        return 0


class 突袭v2(Skill):
    """
    摸牌阶段，你可以少摸任意张牌，然后从相同数量的其他角色处各获得一张手牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "摸牌阶段"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        options = [p for p in game.iterate_live_players() if p is not player and p.hand]
        if not options or not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        targets = [options[i] for i in player.agent().choose_many(options, (1, data), use_skill_event, f"请选择目标角色")]
        print(f"{player}发动了技能{self}，从{'、'.join(str(t) for t in targets)}那里获得了一张手牌")
        for target in targets:
            card = random.choice(target.hand)
            game.lose_card(target, card, "手", "获得", use_skill_event)
            player.hand.append(card)
        return data - len(targets)


突袭 = 突袭v2


class 裸衣(Skill):
    """
    摸牌阶段，你可以少摸一张牌，然后本回合你为伤害来源的【杀】或【决斗】造成的伤害+1。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = False

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what in ["摸牌阶段", "造成伤害时", "turn_end"]

    def use(self, player, event, data=None):
        if event.what == "摸牌阶段":
            use_skill_event = UseSkillEvent(player, self, cause=event)
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}，少摸了一张牌")
                self.buff = True
                return data - 1
            else:
                return data
        elif event.what == "turn_end":
            self.buff = False
            return
        # 造成伤害时 <- damage <- use_card
        event0 = event.cause.cause
        if self.buff and event0.what == "use_card" and (issubclass(event0.card_type, (C_("杀"), C_("决斗")))):
            print(f"{player}的技能{self}被触发，伤害+1")
            return data + 1
        else:
            return data


class 天妒(Skill):
    """
    当你的判定牌生效后，你可以获得此牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "judged"

    def use(self, player, event, data=None):
        game = player.game
        judgment = event.args["result"]
        use_skill_event = UseSkillEvent(player, self, [], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            player.hand.append(judgment)
            game.table.remove(judgment)
            print(f"{player}发动了技能{self}，获得了判定牌{judgment}")


class 遗计(Skill):
    """
    当你受到1点伤害后，你可以观看牌堆顶的两张牌，然后交给任意名角色。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        return player is self.owner and event.who is player and event.what == "受到伤害后"

    def use(self, player, event, data=None):
        game = player.game
        n = event.cause.n
        use_skill_event = UseSkillEvent(player, self, [], event)
        all_players = list(game.iterate_live_players())
        for _ in range(n):
            if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}")
                cards = [game.draw_from_deck() for _ in range(2)]
                while cards:
                    card = cards[player.agent().choose(cards, use_skill_event, f"请选择一张由{self}得到的牌")]
                    target = all_players[player.agent().choose(all_players, use_skill_event, f"请选择要将牌交给的角色")]
                    cards.remove(card)
                    target.hand.append(card)
                    print(f"{player}将一张由{self}得到的牌交给了{target}")


class 倾国(Skill):
    """
    你可以将一张黑色手牌当【闪】使用或打出。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.who is player and event.what == "card_asked" and
                issubclass(C_("闪"), event.args["card_type"]) and player.cards("手", suits="♠♣"))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards("手", suits="♠♣")
        card = options[player.agent().choose(options, cost_event, "请选择")]
        game.lose_card(player, card, "手", "打出", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当闪打出")
        return C_("闪"), [card]


class 洛神(Skill):
    """
    准备阶段，你可以进行判定，若结果为黑色，你可以重复此流程。然后你获得所有的黑色判定牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_start"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        cards = []
        while game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            judgment = game.judge(player, use_skill_event)
            if judgment.suit in "♠♣":
                game.table.remove(judgment)
                cards.append(judgment)
            else:
                break
        player.hand.extend(cards)
        if cards:
            print(f"{player}获得了{'、'.join(str(c) for c in cards)}")


# ======= 吴 =======

class 制衡(Skill):
    """
    出牌阶段限一次，你可以弃置任意张牌，然后摸等量的牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and player.total_cards() > 0

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        print(f"{player}发动了技能{self}")
        n = player.discard_n_cards((1, player.total_cards()), cost_event)
        game.deal_cards(player, n)
        self.use_quota -= 1


class 救援(Skill):
    """
    主公技，锁定技，其他吴势力角色对你使用【桃】回复的体力值+1。
    """
    labels = {"主公技"}

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player and event.what == "recover"):
            return False
        event0 = event.cause
        return (event0.what == "use_card" and event0.who is not player and event0.who.faction == "吴"
                and issubclass(event0.card_type, C_("桃")))

    def use(self, player, event, data=None):
        print(f"{player}的技能{self}被触发")
        return data + 1


class 奇袭(Skill):
    """
    你可以将一张黑色牌当【过河拆桥】使用。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.who is player and event.what == "play" and
                C_("过河拆桥").can_use(player, []) and player.cards(suits="♠♣"))

    def use(self, player, event, data=None):
        game = player.game
        ctype = C_("过河拆桥")
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(suits="♠♣", return_places=True)
        place, card = options[player.agent().choose(options, cost_event, "请选择")]
        try:
            args = ctype.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要发动技能{self}，但中途取消")
            return
        print(f"{player}发动了技能{self}，将{card}当{ctype.__name__}对{'、'.join(str(target) for target in args)}使用")
        game.lose_card(player, card, place[0], "使用", cost_event)
        game.table.append(card)
        ctype.effect(player, [card], args)


class 克己(Skill):
    """
    若你本回合没有使用或打出过【杀】，则你可以跳过弃牌阶段。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.cool = True

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "use_card":
            return issubclass(event.card_type, C_("杀"))
        elif event.what == "respond":
            return issubclass(event.args["card_type"], C_("杀"))
        elif event.what == "test_skip_phase":
            return event.args["phase"] == "弃牌阶段" and self.cool
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.cool = True
        elif event.what in ["use_card", "respond"]:
            self.cool = False
        else:  # event.what == "test_skip_phase"
            game = player.game
            use_skill_event = UseSkillEvent(player, self, cause=event)
            if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                game.skipped.add("弃牌阶段")
                print(f"{player}发动了技能{self}，跳过了弃牌阶段")


class 苦肉(Skill):
    """
    出牌阶段，你可以失去1点体力，然后摸两张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "play"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        print(f"{player}发动了技能{self}，失去了1点体力")
        game.lose_health(player, 1, cost_event)
        if player.is_alive():
            game.deal_cards(player, 2)


class 英姿v1(Skill):
    """
    摸牌阶段，你可以多摸一张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "摸牌阶段"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}，额外摸了一张牌")
            data += 1
        return data


class 英姿v2(Skill):
    """
    锁定技，摸牌阶段，你多摸一张牌；你的手牌上限等于你的体力上限。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what in ["摸牌阶段", "calc_max_hand"]

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if event.what == "摸牌阶段":
            print(f"{player}的技能{self}被触发，额外摸了一张牌")
            return data + 1
        else:  # calc_max_hand
            n = player.hp_cap
            print(f"{player}的技能{self}被触发，手牌上限等于{n}")
            return n


英姿 = 英姿v2


class 反间v1(Skill):
    """
    出牌阶段限一次，你可令一名其他角色选择一种花色后获得你的一张手牌并展示之，若此牌与所选花色不同，则你对其造成1点伤害。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and player.hand

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self)
        players = [p for p in game.iterate_live_players() if p is not player]
        target = players[player.agent().choose(players, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}对{target}发动了技能{self}")
        use_skill_event.targets = [target]
        suits = "♠♥♣♦"
        suit_picked = suits[target.agent().choose(suits, use_skill_event, "请选择一种花色")]
        print(f"{target}选择了{suit_picked}")
        card = random.choice(player.hand)
        print(f"{target}获得并展示了{player}的手牌{card}")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        game.lose_card(player, card, "手", "获得", cost_event)
        target.hand.append(card)
        if card.suit != suit_picked:
            game.damage(target, 1, player, use_skill_event)
        self.use_quota -= 1


class 反间v2(Skill):
    """
    出牌阶段限一次，你可以展示一张手牌并交给一名其他角色，令其选择一项：
    1. 展示所有手牌，然后弃置与此牌花色相同的所有牌；
    2. 失去1点体力。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and player.hand

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        players = [p for p in game.iterate_live_players() if p is not player]
        target = players[player.agent().choose(players, use_skill_event, f"请选择发动技能{self}的目标")]
        use_skill_event.targets = [target]
        card = player.hand[player.agent().choose(player.hand, cost_event, f"请选择发动技能{self}的手牌")]
        print(f"{player}对{target}发动了技能{self}，展示了手牌{card}并将其交给了{target}")
        game.lose_card(player, card, "手", "获得", cost_event)
        target.hand.append(card)
        options = [f"展示所有手牌，然后弃置{card.suit}花色的所有牌", "失去1点体力"]
        if target.agent().choose(options, use_skill_event, "请选择"):
            game.lose_health(target, 1, use_skill_event)
        else:
            print(f"{player}展示了手牌{'、'.join(str(card) for card in player.hand)}")
            for zone in ["手牌", "装备区的牌"]:
                to_discard = target.cards(zone[0], suits=card.suit)
                if to_discard:
                    print(f"{target}弃置了{zone}{'、'.join(str(c) for c in to_discard)}")
                    for c in to_discard:
                        game.lose_card(target, c, zone[0], "弃置", use_skill_event)
                    game.table.extend(to_discard)
        self.use_quota -= 1


反间 = 反间v2


class 国色(Skill):
    """
    你可以将一张♦牌当【乐不思蜀】使用。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.who is player and event.what == "play" and
                C_("乐不思蜀").can_use(player, []) and player.cards(suits="♦"))

    def use(self, player, event, data=None):
        game = player.game
        ctype = C_("乐不思蜀")
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(suits="♦", return_places=True)
        place, card = options[player.agent().choose(options, cost_event, "请选择")]
        try:
            args = ctype.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要发动技能{self}，但中途取消")
            return
        print(f"{player}发动了技能{self}，将{place}{card}当{ctype.__name__}对{args[0]}使用")
        game.lose_card(player, card, place[0], "使用", cost_event)
        game.table.append(card)
        ctype.effect(player, [card], args)


class 流离(Skill):
    """
    当你成为【杀】的目标时，你可以弃置一张牌并将此【杀】转移给你攻击范围内的一名其他角色（不能是使用此【杀】的角色）。
    """

    def legal_targets(self, player, attacker):
        game = player.game
        # return [p for p in game.iterate_live_players() if p is not attacker and game.can_attack(player, p)]
        return [p for p in game.iterate_live_players() if p is not attacker and C_("杀").target_legal(player, p, [])]

    def can_use(self, player, event):  # confirm_targets <- use_card
        if not (player is self.owner and event.what == "confirm_targets"):
            return False
        event0 = event.cause
        if not (event0.what == "use_card" and issubclass(event0.card_type, C_("杀")) and player in event0.targets):
            return False
        return player.total_cards() > 0 and len(self.legal_targets(player, event0.who)) > 0

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(return_places=True)
        place, card = options[player.agent().choose(options, cost_event, "请选择要弃置的牌")]
        options = self.legal_targets(player, event.cause.who)
        if place[0] == "装":
            key = [k for k in player.装备区 if player.装备区[k] is card][0]
            if key in ["武器", "-1坐骑"]:
                player.remove_card(card)
                options = self.legal_targets(player, event.cause.who)
                player.装备区[key] = card
                if not options:
                    print(f"{player}想要发动技能{self}，但中途取消")
                    return data
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动{self}的目标")]
        use_skill_event.targets = [target]
        print(f"{player}弃置了{place}{card}，对{target}发动了技能{self}")
        game.lose_card(player, card, place[0], "弃置", cost_event)
        game.table.append(card)
        targets = data
        targets.remove(player)
        targets.append(target)
        return targets


class 谦逊(Skill):
    """
    锁定技，你不能成为【乐不思蜀】或【顺手牵羊】的目标。
    """

    def can_use(self, player, event):  # test_target_prohibited <- use_card
        return player is self.owner and event.who is player and event.what == "test_target_prohibited" and \
               issubclass(event.cause.card_type, (C_("顺手牵羊"), C_("乐不思蜀")))

    def use(self, player, event, data=None):
        return True


class 连营(Skill):
    """
    当你失去最后的手牌时，你可以摸一张牌。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.who is player and event.what == "lose_card" and
                event.zone == "手" and not player.hand)

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            game.deal_cards(player, 1)


class 结姻(Skill):
    """
    出牌阶段限一次，你可以选择一名已受伤的男性角色并弃置两张手牌，然后你与其各回复1点体力。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p.male and p.is_wounded() and p is not player]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "turn_start" or
                event.what == "play" and self.use_quota > 0 and len(player.hand) >= 2
                and len(self.legal_targets(player)) > 0)

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self)
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动{self}的目标")]
        use_skill_event.targets = [target]
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.hand
        cards = [options[i] for i in player.agent().choose_many(options, 2, cost_event, "请选择要弃置的手牌")]
        print(f"{player}对{target}发动了技能{self}，弃置了手牌{'、'.join(str(c) for c in cards)}")
        for card in cards:
            game.lose_card(player, card, "手", "弃置", cost_event)
        game.table.extend(cards)
        game.recover(target, 1, use_skill_event)
        if player.is_wounded():
            game.recover(player, 1, use_skill_event)
        self.use_quota -= 1


class 枭姬(Skill):
    """
    当你失去装备区里的一张牌时，你可以摸两张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "lose_card" and event.zone == "装"

    def use(self, player, event, data=None):
        game = player.game
        use_skillevent = UseSkillEvent(player, self, [], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skillevent, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            game.deal_cards(player, 2)


# ======= 群 =======

class 急救(Skill):
    """
    你的回合外，你可以将一张红色牌当【桃】使用。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.who is player and event.what == "card_asked" and
                player.game.current_player() is not player and
                issubclass(C_("桃"), event.args["card_type"]) and player.cards(suits="♥♦"))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(suits="♥♦", return_places=True)
        place, card = options[player.agent().choose(options, cost_event, "请选择")]
        print(f"{player}发动了技能{self}，将{place}{card}当桃使用")
        game.lose_card(player, card, place[0], "使用", cost_event)
        game.table.append(card)
        return C_("桃"), [card]


class 青囊(Skill):
    """
    出牌阶段限一次，你可以弃置一张手牌，然后令一名已受伤的角色回复1点体力。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p.is_wounded()]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "turn_start" or
                event.what == "play" and self.use_quota > 0 and len(player.hand) > 0
                and len(self.legal_targets(player)) > 0)

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self)
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动{self}的目标")]
        use_skill_event.targets = [target]
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        card = player.hand[player.agent().choose(player.hand, cost_event, "请选择要弃置的手牌")]
        game.lose_card(player, card, "手", "弃置", cost_event)
        game.table.append(card)
        print(f"{player}弃置了{card}，对{target}发动了技能{self}")
        game.recover(target, 1, use_skill_event)
        self.use_quota -= 1


class 无双(Skill):
    """
    锁定技，你的【杀】需要两张【闪】才能抵消；与你【决斗】的角色每次需要打出两张【杀】。
    """

    def can_use(self, player, event):  # test_respond_disabled <- card_asked <- use_card
        if not (player is self.owner and event.who is not player and event.what == "test_respond_disabled"):
            return False
        event0 = event.cause.cause
        if event0.what != "use_card":
            return False
        ask_type = event.cause.args["card_type"]
        if issubclass(event0.card_type, C_("杀")):
            return event0.who is player and issubclass(ask_type, C_("闪"))
        elif issubclass(event0.card_type, C_("决斗")):
            return (event0.who is player or event0.who is event.who and player in event0.targets) \
                   and issubclass(ask_type, C_("杀"))
        else:
            return False

    def use(self, player, event, data=None):
        if data:
            return True
        game = player.game
        print(f"{player}的技能{self}被触发")
        card_type = event.cause.cause.card_type
        target = event.who
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if issubclass(card_type, C_("杀")):
            responded, _ = game.ask_for_response(target, C_("闪"), use_skill_event, "请选择是否用闪来响应杀")
            return not responded
        else:  # 决斗
            responded, _ = game.ask_for_response(target, C_("杀"), use_skill_event, "请选择是否用杀来响应决斗")
            return not responded


class 离间(Skill):
    """
    出牌阶段限一次，你可以弃置一张牌并选择两名男性角色，然后令其中一名男性角色视为对另一名男性角色使用一张【决斗】。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def legal_targets(self, player):
        game = player.game
        for p in game.iterate_live_players():
            if p is player or not p.male or not C_("决斗").can_use(p, []):
                continue
            if next(self.legal_second_args(player, p), None) is not None:
                yield p

    def legal_second_args(self, player, first_arg):
        game = player.game
        for p in game.iterate_live_players():
            if p is not player and p.male and C_("决斗").target_legal(first_arg, p, []):
                yield p

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "turn_start" or
                event.what == "play" and self.use_quota > 0 and player.total_cards() > 0
                and next(self.legal_targets(player), None) is not None)

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        options = list(self.legal_targets(player))
        target = options[player.agent().choose(options, use_skill_event, f"请选择决斗的使用者")]
        use_skill_event.targets = [target]
        options = list(self.legal_second_args(player, target))
        second_arg = options[player.agent().choose(options, use_skill_event, f"请选择决斗的目标")]
        use_skill_event.targets.append(second_arg)
        print(f"{player}对{target}、{second_arg}发动了技能{self}，视为{target}对{second_arg}使用了决斗")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        player.discard_n_cards(1, cost_event)
        C_("决斗").effect(target, [], [second_arg])
        self.use_quota -= 1


class 闭月(Skill):
    """
    结束阶段，你可以摸一张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_end"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            game.deal_cards(player, 1)


## ======= 神话再临 =======
# ======= 蜀 =======
class 烈弓(Skill):
    """
    当你于出牌阶段内使用【杀】指定一个目标后，若该角色手牌数不小于你的体力值或不大于你的攻击范围，则你可以令其不能使用【闪】响应此【杀】。
    """

    def can_use(self, player, event):  # test_respond_disabled <- card_asked <- use_card
        game = player.game
        if not (player is self.owner and event.what == "test_respond_disabled" and player is game.current_player()):
            return False
        event0 = event.cause.cause
        if not (event0.who is player and event0.what == "use_card" and issubclass(event0.card_type, C_("杀"))):
            return False
        n = len(event.who.hand)
        return n >= player.hp or n <= player.attack_range()

    def use(self, player, event, data=None):
        if data:
            return True
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [event.who], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            return True
        return False


class 狂骨(Skill):
    """
    锁定技，每当你对距离1以内的一名角色造成1点伤害后，若你已受伤，你回复1点体力，否则你摸一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.activate = False

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "造成伤害时":  # 造成伤害时 <- damage
            return True  # Need to add this part because when killing a character, distance becomes inf
        elif event.what == "造成伤害后":  # 造成伤害后 <- damage
            return self.activate
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if event.what == "造成伤害时":
            self.activate = (game.distance(player, event.cause.whom) <= 1)
            return data
        # event.what == "造成伤害后"
        print(f"{player}的技能{self}被触发")
        n = event.cause.n
        n_recover = min(n, player.hp_cap - player.hp)
        n_draw = n - n_recover
        if n_recover > 0:
            game.recover(player, n_recover, use_skill_event)
        if n_draw > 0:
            game.deal_cards(player, n_draw)
        self.activate = False


class 奇谋(Skill):
    """
    限定技，出牌阶段，你可以失去任意点体力，然后本回合你计算与其他角色的距离-X，且你可以多使用X张【杀】（X为你失去的体力值）。
    """

    labels = {"限定技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False
        self.n = 0

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "play":
            return not self.used
        elif event.what == "calc_distance":
            return self.n > 0
        elif event.what == "turn_end":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "calc_distance":
            return data - self.n
        elif event.what == "turn_end":
            self.n = 0
            return
        # event.what == "play"
        use_skill_event = UseSkillEvent(player, self)
        options = list(range(1, player.hp + 1))
        n = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}失去的体力值")]
        print(f"{player}发动了技能{self}，失去了{n}点体力")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        game.lose_health(player, n, cost_event)
        self.n = n
        game.attack_quota += n
        self.used = True


class 连环(Skill):
    """
    你可以将一张♣手牌当【铁索连环】使用或重铸。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.who is player and event.what == "play" and
                C_("铁索连环").can_use(player, []) and player.cards("手", suits="♣"))

    def use(self, player, event, data=None):
        game = player.game
        ctype = C_("铁索连环")
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards("手", suits="♣")
        card = options[player.agent().choose(options, cost_event, "请选择")]
        if player.agent().choose(["使用", "重铸"], use_skill_event, "请选择"):
            print(f"{player}发动了技能{self}，将{card}当{ctype.__name__}重铸")
            game.lose_card(player, card, "手", "重铸", cost_event)
            game.table.append(card)
            game.deal_cards(player, 1)
            return
        try:
            args = ctype.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要发动技能{self}，但中途取消")
            return
        game.lose_card(player, card, "手", "使用", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当{ctype.__name__}对{'、'.join(str(target) for target in args)}使用")
        ctype.effect(player, [card], args)


class 涅槃(Skill):
    """
    限定技，当你处于濒死状态时，你可以弃置你的区域里的所有牌，然后复原你的武将牌，摸三张牌，将体力回复至3点。
    """
    labels = {"限定技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "dying" and \
               not self.used and player.hp <= 0

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        print(f"{player}发动了技能{self}")
        game.discard_all_cards(player, "手装判", use_skill_event)
        if player.chained:
            game.chain(player, use_skill_event)
        if player.flipped:
            game.flip(player, use_skill_event)
        game.deal_cards(player, 3)
        n = 3 - player.hp
        game.recover(player, n, use_skill_event)
        self.used = True


from cardtype import 八卦阵特效


class 八阵(八卦阵特效):
    """
    锁定技，若你的装备区里没有防具牌，你视为装备着【八卦阵】。
    """

    def can_use(self, player, event):  # pre_card_asked(player) <- card_asked(player, 闪) <- use_card(user, 杀/万箭齐发)
        return player is self.owner and "防具" not in player.装备区 and super().can_use(player, event)


class 火计(Skill):
    """
    你可以将一张红色手牌当【火攻】使用。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.who is player and event.what == "play" and
                C_("火攻").can_use(player, []) and player.cards("手", suits="♥♦"))

    def use(self, player, event, data=None):
        game = player.game
        ctype = C_("火攻")
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards("手", suits="♥♦")
        card = options[player.agent().choose(options, cost_event, "请选择")]
        try:
            args = ctype.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要发动技能{self}，但中途取消")
            return
        game.lose_card(player, card, "手", "使用", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当{ctype.__name__}对{'、'.join(str(target) for target in args)}使用")
        ctype.effect(player, [card], args)


class 看破(Skill):
    """
    你可以将一张黑色手牌当【无懈可击】使用。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.who is player and event.what == "card_asked" and
                issubclass(C_("无懈可击"), event.args["card_type"]) and player.cards("手", suits="♠♣"))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards("手", suits="♠♣")
        card = options[player.agent().choose(options, cost_event, "请选择")]
        game.lose_card(player, card, "手", "使用", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当无懈可击打出")
        return C_("无懈可击"), [card]


class 挑衅(Skill):
    """
    出牌阶段限一次，你可以指定一名你在其攻击范围内的角色，然后其需对你使用一张【杀】，否则令你弃置其一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players()
                if p is not player and player.game.distance(p, player) <= p.attack_range()]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "turn_start" or
                event.what == "play" and self.use_quota > 0 and self.legal_targets(player))

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self)
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}对{target}发动了技能{self}")
        use_skill_event.targets = [target]
        ctype, cards = game.ask_for_response(target, C_("杀"), use_skill_event,
                                                f"请选择是否对{player}使用杀", verb="使用")
        if ctype:
            ctype.effect(target, cards, [player])
        else:
            place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择发动技能{self}弃置的牌")
            if card:
                print(f"{player}弃置了{target}的{place}{card}")
                game.lose_card(target, card, place[0], "弃置", use_skill_event)
                game.table.append(card)
        self.use_quota -= 1


class 志继(Skill):
    """
    觉醒技，准备阶段，若你没有手牌，你回复1点体力或摸两张牌，减1点体力上限，然后获得技能“观星”。
    """
    labels = {"觉醒技"}

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "before_turn_start" and not player.hand

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self)
        print(f"{player}的技能{self}被触发，减了1点体力上限，并获得了技能“观星”")
        game.change_hp_cap(player, -1, use_skill_event)
        options = ["摸两张牌"]
        if player.is_wounded():
            options.append("回复1点体力")
        if player.agent().choose(options, use_skill_event, f"请选择"):
            game.recover(player, 1, use_skill_event)
        else:
            game.deal_cards(player, 2)
        player.skills = player.skills[:]  # Avoid modifying the list when iterating through it in Game.trigger_skills()
        player.skills.remove(self)
        new_skill = 观星(player)
        # new_skill.use(player, event, data)  # This skill will not be iterated this time, so call it explicitly
        player.skills.append(new_skill)
        game.trigger_skills(Event(player, "wake"))


class 享乐(Skill):
    """
    锁定技，当你成为一名角色【杀】的目标后，除非该角色弃置一张基本牌，否则此【杀】对你无效。
    """

    def can_use(self, player, event):  # test_card_nullify(player) <- use_card(attacker, 杀)
        return (player is self.owner and event.who is player and event.what == "test_card_nullify"
                and issubclass(event.cause.card_type, C_("杀")))

    def use(self, player, event, data=None):
        game = player.game
        target = event.cause.who
        use_skill_event = UseSkillEvent(player, self, [target], event)
        print(f"{player}的技能{self}被触发，{target}需弃置一张基本牌，否则此杀无效")
        options = [None] + target.cards("手", types=C_("基本牌"))
        discard_event = Event(target, "discard", use_skill_event)
        card = options[target.agent().choose(options, discard_event, f"请选择弃置的基本牌")]
        if card:
            print(f"{target}弃置了{card}")
            game.lose_card(target, card, "手", "弃置", discard_event)
            game.table.append(card)
            return False
        else:
            return True


class 放权(Skill):
    """
    你可以跳过出牌阶段，然后此回合结束时，你可以弃置一张手牌并令一名其他角色获得一个额外的回合。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.skipped_play = False

    def can_use(self, player, event):
        game = player.game
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "test_skip_phase" and event.args["phase"] == "出牌阶段" and "出牌阶段" not in game.skipped
                or event.what == "turn_end" and self.skipped_play and player.hand)

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "test_skip_phase":
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}")
                game.skipped.add("出牌阶段")
                self.skipped_play = True
            else:
                self.skipped_play = False
            return
        # event.what == "turn_end"
        options = [None] + player.cards("手")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        card = options[player.agent().choose(options, cost_event, f"请选择是否发动技能{self}")]
        if not card:
            return
        players = [p for p in game.iterate_live_players() if p is not player]
        target = players[player.agent().choose(players, use_skill_event, f"请选择发动技能{self}使其获得一个额外的回合的角色")]
        print(f"{player}发动了技能{self}，弃置了手牌{card}，令{target}获得一个额外的回合")
        game.lose_card(player, card, "手", "弃置", cost_event)
        game.table.append(card)
        game.current_pid = target.pid()
        game.run_turn()
        game.current_pid = player.pid()


class 若愚(Skill):
    """
    主公技，觉醒技，准备阶段，若你是体力值最小的角色，你加1点体力上限，回复1点体力，然后获得“激将”。
    """
    labels = {"主公技", "觉醒技"}

    def can_use(self, player, event):
        game = player.game
        return (player is self.owner and event.who is player and event.what == "before_turn_start"
                and player.hp == min(p.hp for p in game.iterate_live_players()))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, event)
        print(f"{player}的技能{self}被触发，加了1点体力上限，并获得了技能“激将”")
        game.change_hp_cap(player, +1, use_skill_event)
        game.recover(player, 1, use_skill_event)
        player.skills = player.skills[:]  # Avoid modifying the list when iterating through it in Game.trigger_skills()
        player.skills.remove(self)
        player.skills.append(激将(player))
        game.trigger_skills(Event(player, "wake"))


class 祸首(Skill):
    """
    锁定技，【南蛮入侵】对你无效；其他角色使用【南蛮入侵】指定目标后，你代替其成为此牌造成伤害的来源。
    """

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        ctype = C_("南蛮入侵")
        if event.what == "test_card_nullify":  # test_card_nullify(player) <- use_card(attacker, 南蛮入侵)
            return event.who is player and issubclass(event.cause.card_type, ctype)
        elif event.what == "modify_damage_inflicter":  # modify_damage_inflicter(damaged) <- use_card(user, 南蛮入侵)
            event0 = event.cause
            return event0.what == "use_card" and event0.who is not player and issubclass(event0.card_type, ctype)
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "test_card_nullify":
            print(f"{player}的技能{self}被触发，南蛮入侵对{player}无效")
            return True
        elif event.what == "modify_damage_inflicter":
            print(f"{player}的技能{self}被触发，南蛮入侵的伤害来源改为{player}")
            return player
        else:
            return data


class 再起(Skill):
    """
    摸牌阶段，若你已受伤，你可以放弃摸牌改为展示牌堆顶的X张牌（X为你已损失的体力值），
    其中每有一张♥牌，你回复1点体力，然后弃置这些♥牌，并获得其余的牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "摸牌阶段" and player.is_wounded()

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        cards = [game.draw_from_deck() for _ in range(player.hp_cap - player.hp)]
        print(f"{player}发动了技能{self}，亮出了{'、'.join(str(c) for c in cards)}")
        to_keep, to_discard = [], []
        for card in cards:
            if card.suit == "♥":
                to_discard.append(card)
            else:
                to_keep.append(card)
        if to_discard:
            game.recover(player, len(to_discard), use_skill_event)
            game.table.extend(to_discard)
            print(f"{'、'.join(str(c) for c in to_discard)}被弃置")
        if to_keep:
            player.hand.extend(to_keep)
            print(f"{player}获得了{'、'.join(str(c) for c in to_keep)}")
        return 0


class 巨象(Skill):
    """
    锁定技，【南蛮入侵】对你无效；当其他角色使用的【南蛮入侵】结算结束后，你获得之。
    """

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        ctype = C_("南蛮入侵")
        if event.what == "test_card_nullify":  # test_card_nullify(player) <- use_card(attacker, 南蛮入侵)
            return event.who is player and issubclass(event.cause.card_type, ctype)
        # TODO: get 南蛮入侵 played by other players
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "test_card_nullify":
            print(f"{player}的技能{self}被触发，南蛮入侵对{player}无效")
            return True
        else:
            return data


class 烈刃(Skill):
    """
    当你使用【杀】对目标角色造成伤害后，你可以与其拼点，若你赢，你获得其一张牌。
    """

    def can_use(self, player, event):  # 造成伤害后 <- damage <- use_card
        if not (player is self.owner and event.who is player and event.what == "造成伤害后"):
            return False
        event0 = event.cause.cause
        return event0.who is player and event0.what == "use_card" and issubclass(event0.card_type, C_("杀")) \
               and player.hand and event.cause.whom.hand

    def use(self, player, event, data=None):
        game = player.game
        target = event.cause.whom
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        print(f"{player}对{target}发动了技能{self}")
        winner, _, _ = game.拼点(player, target, use_skill_event)
        if winner is not player:
            return
        place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择发动技能{self}获取的牌")
        if card:
            if place[0] == "手":
                print(f"{player}获得了{target}的一张手牌")
            else:
                print(f"{player}获得了{target}的{place}{card}")
            game.lose_card(target, card, place[0], "获得", use_skill_event)
            player.hand.append(card)


# ======= 魏 =======
class 神速(Skill):
    """
    你可以选择一至两项：1. 跳过判定阶段和摸牌阶段；2. 跳过出牌阶段并弃置一张装备牌。你每选择一项，视为你使用一张无距离限制的【杀】。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = False

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "test_skip_phase":
            phase = event.args["phase"]
            return phase in ["判定阶段", "出牌阶段"] and phase not in player.game.skipped
        elif event.what == "modify_use_range":
            return self.buff and issubclass(event.args["card_type"], C_("杀"))
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "modify_use_range":
            return None
        # event.what == "test_skip_phase"
        game = player.game
        phase = event.args["phase"]
        if phase in game.skipped:
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if phase == "判定阶段":
            if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}跳过判定阶段和摸牌阶段"):
                return
            game.skipped.add("判定阶段")
            game.skipped.add("摸牌阶段")
            print(f"{player}发动了技能{self}，跳过了判定阶段和摸牌阶段")
        else:  # phase == "出牌阶段"
            options = player.cards(types=C_("装备牌"), return_places=True)
            if not options or not player.agent().choose(["不发动", "发动"], use_skill_event,
                                                        f"请选择是否发动技能{self}跳过出牌阶段"):
                return
            game.skipped.add("出牌阶段")
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            place, card = options[player.agent().choose(options, cost_event, "请选择要弃置的装备牌")]
            print(f"{player}发动了技能{self}，跳过了出牌阶段并弃置了{place}{card}")
            game.lose_card(player, card, place[0], "弃置", cost_event)
            game.table.append(card)
        ctype = C_("杀")
        self.buff = True
        target_choices = [p for p in game.iterate_live_players() if ctype.target_legal(player, p, [])]
        self.buff = False
        if not target_choices:
            return
        target = target_choices[player.agent().choose(target_choices, use_skill_event, f"请选择发动技能{self}杀的目标")]
        print(f"{player}视为对{target}使用了一张杀")
        ctype.effect(player, [], [target])
        game.attack_quota += 1  # The 杀 is not supposed to count in terms of attack quota, so add it back


class 巧变(Skill):
    """
    你可以弃置一张手牌，跳过除准备阶段和结束阶段外的一个阶段，然后若你以此法：
    跳过摸牌阶段，你可以获得一至两名其他角色的各一张手牌；
    跳过出牌阶段，你可以将一名角色装备区或判定区的一张牌置入另一名角色的相应区域（不得替换原有的牌）。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player and event.what == "test_skip_phase"):
            return False
        return event.args["phase"] not in player.game.skipped and player.hand

    def use(self, player, event, data=None):
        game = player.game
        phase = event.args["phase"]
        if phase in game.skipped:
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}跳过{phase}"):
            return
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        card = player.hand[player.agent().choose(player.hand, cost_event, f"请选择发动技能{self}弃置的手牌")]
        print(f"{player}发动了技能{self}，弃置了手牌{card}，跳过了{phase}")
        game.lose_card(player, card, "手", "弃置", cost_event)
        game.table.append(card)
        game.skipped.add(phase)
        if phase == "摸牌阶段":
            options = [p for p in game.iterate_live_players() if p is not player and p.hand]
            if not options:
                return
            targets = [options[i] for i in player.agent().choose_many(options, (1, 2), use_skill_event, "请选择目标角色")]
            print(f"{player}从{'、'.join(str(t) for t in targets)}那里获得了一张手牌")
            for target in targets:
                card = random.choice(target.hand)
                game.lose_card(target, card, "手", "获得", use_skill_event)
                player.hand.append(card)
        elif phase == "出牌阶段":
            options = [p for p in game.iterate_live_players() if p.cards("装判")]
            if not options:
                return
            target = options[player.agent().choose(options, use_skill_event, f"请选择发动{self}移走装备区或判定区的牌的角色")]
            place, card = game.pick_card(player, target, "装判", use_skill_event,
                                         f"请选择发动{self}移走的{target}的装备区或判定区的牌")
            if place[0] == "装":
                key = None
                for k, val in target.装备区.items():
                    if val is card:
                        key = k
                        break
                options = [p for p in game.iterate_live_players() if p is not target and key not in p.装备区]
            else:  # place[0] == "判"
                key = None
                for k, val in target.判定区.items():
                    if val is card:
                        key = k
                        break
                options = [p for p in game.iterate_live_players() if p is not target and key not in p.判定区]
            if not options:
                return
            second_arg = options[player.agent().choose(options, use_skill_event,
                                                       f"请选择发动{self}将{target}{place}{card}转移给哪名角色")]
            print(f"{player}将{target}{place}{card}转移给了{second_arg}")
            game.lose_card(target, card, place[0], "置入", use_skill_event)
            if place[0] == "装":
                second_arg.装备区[key] = card
            else:  # place[0] == "判"
                second_arg.判定区[key] = card


class 断粮(Skill):
    """
    你可以将一张黑色基本牌或黑色装备牌当【兵粮寸断】使用；你可以对距离为2的角色使用【兵粮寸断】。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        ctype = C_("兵粮寸断")
        if event.what == "play":
            return ctype.can_use(player, []) and player.cards(suits="♠♣", types=(C_("基本牌"), C_("装备牌")))
        elif event.what == "modify_use_range":
            return issubclass(event.args["card_type"], ctype)
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "modify_use_range":
            return 2
        # event.what == "play"
        ctype = C_("兵粮寸断")
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(suits="♠♣", types=(C_("基本牌"), C_("装备牌")), return_places=True)
        place, card = options[player.agent().choose(options, cost_event, "请选择")]
        try:
            args = ctype.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要发动技能{self}，但中途取消")
            return
        print(f"{player}发动了技能{self}，将{card}当{ctype.__name__}对{args[0]}使用")
        game.lose_card(player, card, place[0], "使用", cost_event)
        game.table.append(card)
        ctype.effect(player, [card], args)


class 据守(Skill):
    """
    回合结束阶段，你可以摸四张牌，若如此做，将你的武将牌翻面
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_end"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            game.deal_cards(player, 4)
            game.flip(player)


class 强袭(Skill):
    """
    出牌阶段限一次，你可以失去1点体力或弃置一张武器牌，然后对你攻击范围内的一名其他角色造成1点伤害。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def legal_targets(self, player):
        game = player.game
        return [p for p in game.iterate_live_players() if p is not player
                and game.distance(player, p) <= player.attack_range()]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "turn_start" or
                event.what == "play" and self.use_quota > 0 and self.legal_targets(player))

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self)
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
        use_skill_event.targets = [target]
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards("手", types=C_("武器"), return_places=True)
        if "武器" in player.装备区 and game.distance(player, target) == 1:
            options.append(("装备区的牌", player.装备区["武器"]))
        options = ["不弃置"] + options
        choice = player.agent().choose(options, cost_event, "请选择要弃置的武器牌")
        if not choice:
            print(f"{player}对{target}发动了技能{self}，失去了1点体力")
            game.lose_health(player, 1, cost_event)
        else:
            place, card = options[choice]
            print(f"{player}对{target}发动了技能{self}，弃置了{place}{card}")
            game.lose_card(player, card, place[0], "弃置", cost_event)
            game.table.append(card)
        game.damage(target, 1, player, use_skill_event)
        self.use_quota -= 1


class 驱虎(Skill):
    """
    出牌阶段限一次，你可以与一名体力值大于你的角色拼点：
    若你赢，该角色对其攻击范围内你选择的一名角色造成1点伤害；
    若你没赢，该角色对你造成1点伤害。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p.hp > player.hp and p.hand]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "turn_start" or
                event.what == "play" and self.use_quota > 0 and len(player.hand) > 0 and self.legal_targets(player))

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self)
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}对{target}发动了技能{self}")
        use_skill_event.targets = [target]
        winner, _, _ = game.拼点(player, target, use_skill_event)
        if winner is player:
            options = [p for p in game.iterate_live_players()
                       if p is not target and game.distance(target, p) <= target.attack_range()]
            if options:
                event2 = core.Event(player, "get_indirect_target", use_skill_event, whom=target)  # 驱虎, 明策
                victim = options[player.agent().choose(options, event2, f"请选择受到技能{self}伤害的对象")]
                game.damage(victim, 1, target, use_skill_event)
        else:
            game.damage(player, 1, target, use_skill_event)
        self.use_quota -= 1


class 节命(Skill):
    """
    当你受到1点伤害后，你可以令一名角色将手牌摸至X张（X为其体力上限且最多为5）。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        return player is self.owner and event.who is player and event.what == "受到伤害后"

    def use(self, player, event, data=None):
        game = player.game
        n = event.cause.n
        use_skill_event = UseSkillEvent(player, self, [], event)
        all_players = list(game.iterate_live_players())
        for _ in range(n):
            if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                target = all_players[player.agent().choose(all_players, use_skill_event, f"请选择发动技能{self}补牌的角色")]
                print(f"{player}对{target}发动了技能{self}")
                n = max(0, min(target.hp_cap, 5) - len(target.hand))
                game.deal_cards(target, n)


class 行殇(Skill):
    """
    当其他角色死亡时，你可以获得其所有牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is not player and event.what == "die" and event.who.cards()

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            the_dead = event.who
            print(f"{player}发动了技能{self}")
            if the_dead.hand:
                print(f"{player}获得了{the_dead}的{len(the_dead.hand)}张手牌")
                player.hand.extend(the_dead.hand)
                the_dead.hand = []
            equips = the_dead.cards("装")
            if equips:
                print(f"{player}获得了{the_dead}的装备区的牌{'、'.join(str(c) for c in equips)}")
                player.hand.extend(equips)
                the_dead.装备区 = {}


class 放逐(Skill):
    """
    当你受到伤害后，你可以令一名其他角色翻面，然后该角色摸X张牌（X为你已损失的体力值）。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        return player is self.owner and event.who is player and event.what == "受到伤害后"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            players = [p for p in game.iterate_live_players() if p is not player]
            target = players[player.agent().choose(players, use_skill_event, f"请选择发动技能{self}的目标")]
            print(f"{player}对{target}发动了技能{self}")
            game.flip(target)
            if player.is_wounded():
                game.deal_cards(target, player.hp_cap - player.hp)


class 颂威(Skill):
    """
    主公技，当其他魏势力角色的黑色判定牌生效后，其可以令你摸一张牌。
    """
    labels = {"主公技"}

    def can_use(self, player, event):
        if not (player is not self.owner and event.who is player and event.what == "judged"):
            return False
        return player.faction == "魏" and event.args["result"].suit in "♠♣"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动{self.owner}的技能{self}"):
            print(f"{player}发动了{self.owner}的技能{self}")
            game.deal_cards(self.owner, 1)


class 屯田(Skill):
    """
    当你于回合外失去牌后，你可以进行判定，若结果不为♥，你可将判定牌置于武将牌上，称为“田”；你计算与其他角色的距离-X（X为“田”的数量）。
    """

    def can_use(self, player, event):
        game = player.game
        return player is self.owner and event.who is player and \
               (event.what == "lose_card" and event.zone in "手装" and player is not game.current_player() or
                event.what == "calc_distance")

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "calc_distance":
            return data - len(player.repo)
        # event.what == "lose_card
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not (game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}")):
            return
        print(f"{player}发动了技能{self}")
        judgment = game.judge(player, use_skill_event)
        if judgment.suit == "♥":
            print(f"{player}的技能{self}发动失败")
            return
        print(f"{player}的技能{self}生效，将{judgment}置于武将牌上作为“田")
        game.table.remove(judgment)
        player.repo.append(judgment)


class 凿险(Skill):
    """
    觉醒技，准备阶段，若“田”的数量不小于3，你减1点体力上限，然后获得技能“急袭”。
    """
    labels = {"觉醒技"}

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "before_turn_start" \
               and len(player.repo) >= 3

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        print(f"{player}的技能{self}被触发，减了1点体力上限，并获得了技能“急袭”")
        game.change_hp_cap(player, -1, use_skill_event)
        player.skills = player.skills[:]  # Avoid modifying the list when iterating through it in Game.trigger_skills()
        player.skills.remove(self)
        player.skills.append(急袭(player))
        game.trigger_skills(Event(player, "wake"))


class 急袭(Skill):
    """
    你可以将一张“田”当【顺手牵羊】使用。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.who is player and event.what == "play" and
                C_("顺手牵羊").can_use(player, []) and player.repo)

    def use(self, player, event, data=None):
        game = player.game
        ctype = C_("顺手牵羊")
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.repo
        card = options[player.agent().choose(options, cost_event, f"请选择用来发动技能{self}一张“田”")]
        player.repo.remove(card)  # Remove before get_args because the number of 田 affects legal targets of 顺手牵羊
        try:
            args = ctype.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要发动技能{self}，但中途取消")
            player.repo.append(card)
            return
        print(f"{player}发动了技能{self}，将一张“田”（{card}）当{ctype.__name__}"
              f"对{'、'.join(str(target) for target in args)}使用")
        game.table.append(card)
        ctype.effect(player, [card], args)


# ======= 吴 =======
class 英魂(Skill):
    """
    准备阶段，若你已受伤，你可以令一名其他角色：摸X张牌，然后弃置一张牌；或摸一张牌，然后弃置X张牌（X为你已损失的体力值）。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_start" and player.is_wounded()

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        players = [p for p in game.iterate_live_players() if p is not player]
        target = players[player.agent().choose(players, use_skill_event, f"请选择发动技能{self}的目标角色")]
        n = player.hp_cap - player.hp
        if n == 1:
            n_draw = n_discard = 1
        else:
            if player.agent().choose([f"摸{n}张牌，然后弃置一张牌", f"摸一张牌，然后弃置{n}张牌"], use_skill_event, "请选择"):
                n_draw, n_discard = 1, n
            else:
                n_draw, n_discard = n, 1
        print(f"{player}发动了技能{self}，令{target}摸{n_draw}张牌，然后弃置{n_discard}张牌")
        game.deal_cards(target, n_draw)
        target.discard_n_cards(n_discard, use_skill_event)


class 激昂(Skill):
    """
    每当你使用（指定目标后）或被使用（成为目标后）一张【决斗】或红色的【杀】时，你可以摸一张牌。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.what == "use_card" and (event.who is player or player in event.targets)):
            return False
        return issubclass(event.card_type, C_("决斗")) or \
               issubclass(event.card_type, C_("杀")) and core.color(event.cards) == "red"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            player.game.deal_cards(player, 1)


class 魂姿(Skill):
    """
    觉醒技，准备阶段，若你的体力值为1，你减1点体力上限，然后获得技能“英姿”和“英魂”。
    """
    labels = {"觉醒技"}

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "before_turn_start" and player.hp == 1

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        print(f"{player}的技能{self}被触发，减了1点体力上限，并获得了技能“英姿”和“英魂”")
        game.change_hp_cap(player, -1, use_skill_event)
        player.skills = player.skills[:]  # Avoid modifying the list when iterating through it in Game.trigger_skills()
        player.skills.remove(self)
        player.skills.append(英姿(player))
        new_skill = 英魂(player)
        # new_skill.use(player, event, data)  # This skill will not be iterated this time, so call it explicitly
        player.skills.append(new_skill)
        game.trigger_skills(Event(player, "wake"))


class 制霸(Skill):
    """
    主公技，其他吴势力角色的出牌阶段限一次，该角色可以与你拼点（若你已觉醒，你可以拒绝此拼点）；若其没赢，你可以获得拼点的两张牌。
    """
    labels = {"主公技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1
        self.awaken = False

    def can_use(self, player, event):
        if player is self.owner and event.who is player and event.what == "wake":
            return True
        if not (player is not self.owner and player.faction == "吴" and event.who is player):
            return False
        return (event.what == "turn_start" or
                event.what == "play" and self.use_quota > 0 and player.hand and self.owner.hand)

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "wake":
            self.awaken = True
            return
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self, [self.owner])
        if self.awaken and self.owner.agent().choose(["接受", "拒绝"],
                                                     use_skill_event, f"{player}想要发动你的技能{self}与你拼点，是否接受？"):
            return
        print(f"{player}发动了{self.owner}的技能{self}")
        winner, card1, card2 = game.拼点(player, self.owner, use_skill_event)
        if winner is self.owner:
            print(f"{self.owner}获得了拼点的牌{card1}、{card2}")
            for card in [card1, card2]:
                game.table.remove(card)
                self.owner.hand.append(card)
        self.use_quota -= 1


class 天香(Skill):
    """
    当你受到伤害时，你可以弃置一张♥手牌并选择一名其他角色。若如此做，你将此伤害转移给该角色，然后其摸X张牌（X为该角色已损失的体力值）。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "受到伤害时" and \
               player.cards("手", suits="♥♠")

    def use(self, player, event, data=None):
        if data <= 0:
            return data
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards("手", suits="♥♠")
        card = options[player.agent().choose(options, cost_event, "请选择弃置的手牌")]
        options = [p for p in game.iterate_live_players() if p is not player]
        target = options[player.agent().choose(options, use_skill_event, "请选择转移伤害的目标")]
        use_skill_event.targets = [target]
        print(f"{player}发动了技能{self}，弃置了手牌{card}，将伤害转移给了{target}")
        game.lose_card(player, card, "手", "弃置", cost_event)
        game.discard([card])
        game.damage(target, data, event.cause.who, use_skill_event,
                    event.cause.type)  # TODO: See skill FAQ for special cases
        if target.is_alive():
            game.deal_cards(target, target.hp_cap - target.hp)
        return 0


class 红颜(Skill):
    """
    锁定技，你的♠牌视为♥牌。
    """
    # TODO: 红颜


class 天义(Skill):
    """
    出牌阶段限一次，你可以与一名角色拼点：
    若你赢，本回合你可以多使用一张【杀】，使用【杀】无距离限制且可以多选择一个目标；
    若你没赢，本回合你不能使用【杀】。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = None

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p is not player and p.hand]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "play":
            return not self.buff and len(player.hand) > 0 and self.legal_targets(player)
        elif event.what in ["modify_use_range", "modify_n_targets"]:
            return self.buff == "good" and issubclass(event.args["card_type"], C_("杀"))
        elif event.what == "test_use_prohibited":
            return self.buff == "bad" and issubclass(event.args["card_type"], C_("杀"))
        elif event.what == "turn_end":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "modify_use_range":
            return None
        elif event.what == "modify_n_targets":
            return data + 1
        elif event.what == "test_use_prohibited":
            return True
        elif event.what == "turn_end":
            self.buff = None
            return
        # event.what == "play"
        use_skill_event = UseSkillEvent(player, self)
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}对{target}发动了技能{self}")
        use_skill_event.targets = [target]
        winner, _, _ = game.拼点(player, target, use_skill_event)
        if winner is player:
            self.buff = "good"
            game.attack_quota += 1
        else:
            self.buff = "bad"


class 不屈(Skill):
    """
    锁定技，当你处于濒死状态时，你将牌堆顶的一张牌置于你的武将牌上，称为“创”：
    若此牌点数与已有的“创”点数均不同，你将体力回复至1点；
    若点数相同，将此牌放入弃牌堆。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "dying" and player.hp <= 0

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        card = game.draw_from_deck()
        print(f"{player}的技能{self}被触发，亮出了牌堆顶的牌{card}")
        good = True
        for c in player.repo:
            if c.rank == card.rank:
                good = False
                break
        if good:
            print(f"{player}将{card}置于武将牌上，称为“创”")
            player.repo.append(card)
            n = 1 - player.hp
            game.recover(player, n, use_skill_event)
        else:
            print(f"{player}的技能{self}发动失败，{card}被放入弃牌堆")
            game.discard([card])


class 好施(Skill):
    """
    摸牌阶段，你可以多摸两张牌，然后若你的手牌数大于5，则你将一半的手牌（向下取整）交给手牌最少的一名其他角色。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "摸牌阶段"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        print(f"{player}发动了技能{self}")
        game.deal_cards(player, 4)
        if len(player.hand) > 5:
            min_hand = min(len(p.hand) for p in game.iterate_live_players() if p is not player)
            players = [p for p in game.iterate_live_players() if p is not player and len(p.hand) == min_hand]
            target = players[player.agent().choose(players, use_skill_event, "请选择要将牌交给的角色")]
            use_skill_event.targets = [target]
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            n = len(player.hand) // 2
            options = player.cards("手")
            cards = [options[i] for i in
                     player.agent().choose_many(options, n, event=cost_event, message=f"请选择发动技能{self}给出的手牌")]
            print(f"{player}发动技能{self}，将{n}张手牌交给了{target}")
            for card in cards:
                game.lose_card(player, card, "手", "获得", cost_event)
            target.hand.extend(cards)
        return 0


class 缔盟(Skill):
    """
    出牌阶段限一次，你可以选择两名其他角色并弃置X张牌（X为这两名角色手牌数的差），然后令这两名角色交换手牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and len(player.game.alive) >= 3

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self)
        players = [p for p in game.iterate_live_players() if p is not player]
        target1 = players[player.agent().choose(players, use_skill_event, f"请选择发动技能{self}的第一个目标")]
        use_skill_event.targets = [target1]
        n1, diff = len(target1.hand), len(player.cards())
        players = [p for p in players if p is not target1 and n1 - diff <= len(p.hand) <= n1 + diff]
        if not players:
            print(f"{player}想要发动技能{self}，但中途取消")
            return
        target2 = players[player.agent().choose(players, use_skill_event, f"请选择发动技能{self}的第二个目标")]
        print(f"{player}发动了技能{self}，令{target1}和{target2}交换手牌")
        use_skill_event.targets.append(target2)
        n2 = len(target2.hand)
        n = abs(n1 - n2)
        if n > 0:
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            player.discard_n_cards(n, cost_event)
        cards1, cards2 = target1.cards("手"), target2.cards("手")
        for card in cards1:
            game.lose_card(target1, card, "手", "获得", use_skill_event)
        for card in cards2:
            game.lose_card(target2, card, "手", "获得", use_skill_event)
        print(f"{target1}获得了{target2}的{len(cards2)}张手牌")
        target1.hand.extend(cards2)
        print(f"{target2}获得了{target1}的{len(cards1)}张手牌")
        target2.hand.extend(cards1)
        self.use_quota -= 1


class 直谏(Skill):
    """
    出牌阶段，你可以将手牌中的一张装备牌放入一名其他角色的装备区里，然后摸一张牌。
    """

    def legal_targets(self, player, card):
        game = player.game
        return [p for p in game.iterate_live_players() if p is not player and card.type.equip_type not in p.装备区]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player and event.what == "play"):
            return False
        cards = player.cards("手", types=C_("装备牌"))
        if not cards:
            return False
        for card in cards:
            if self.legal_targets(player, card):
                return True
        return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cards = player.cards("手", types=C_("装备牌"))
        card = cards[player.agent().choose(cards, use_skill_event, f"请选择发动技能{self}的装备牌")]
        options = self.legal_targets(player, card)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}发动了技能{self}，将{card}放入了{target}的装备区")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        game.lose_card(player, card, "手", "置入", cost_event)
        target.装备区[card.type.equip_type] = card
        game.deal_cards(player, 1)


class 固政(Skill):
    """
    其他角色的弃牌阶段结束时，你可以将此阶段中其弃置的一张手牌返还给该角色，然后你获得其余的弃牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is not player and event.what == "弃牌阶段"

    def use(self, player, event, data=None):
        if not data:
            return data
        target = event.who
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if not data or not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        card = data[player.agent().choose(data, use_skill_event, f"请选择发动技能{self}返还给{target}的牌")]
        data.remove(card)
        str_tail = f"，并获得了{'、'.join(str(c) for c in data)}" if data else ""
        print(f"{player}发动了技能{self}，将{card}返还给了{target}{str_tail}")
        target.hand.append(card)
        player.hand.extend(data)
        return []


# ======= 群 =======
class 乱击v1(Skill):
    """
    你可以将两张花色相同的手牌当【万箭齐发】使用。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player and event.what == "play"):
            return False
        return len(player.hand) > len({card.suit for card in player.hand})

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        ctype = C_("万箭齐发")
        counter = {"♠": 0, "♥": 0, "♣": 0, "♦": 0}
        for card in player.hand:
            counter[card.suit] += 1
        suits = {suit for suit in counter if counter[suit] >= 2}
        options = [card for card in player.hand if card.suit in suits]
        first_card = options[player.agent().choose(options, cost_event, f"请选择发动{self}的第一张手牌")]
        options.remove(first_card)
        options = [card for card in options if card.suit == first_card.suit]
        second_card = options[player.agent().choose(options, cost_event, f"请选择发动{self}的第二张手牌")]
        cards = [first_card, second_card]
        try:
            args = ctype.get_args(player, cards)
        except core.NoOptions:
            print(f"{player}想要发动技能{self}，但中途取消")
            return
        print(f"{player}发动了技能{self}，将{'、'.join(str(card) for card in cards)}当{ctype.__name__}"
              f"对{'、'.join(str(target) for target in args)}使用")
        for card in cards:
            game.lose_card(player, card, "手", "使用", cost_event)
            game.table.append(card)
        ctype.effect(player, cards, args)


class 乱击v2(Skill):
    """
    你可以将两张花色相同的手牌当【万箭齐发】使用（每回合每种花色的牌限一次）。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.suits = set()

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "play":
            cards = player.cards("手", suits=self.suits)
            return len(cards) > len(set(card.suit for card in cards))
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.suits = set("♠♥♣♦")
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        ctype = C_("万箭齐发")
        counter = {"♠": 0, "♥": 0, "♣": 0, "♦": 0}
        for card in player.cards("手", suits=self.suits):
            counter[card.suit] += 1
        suits = {suit for suit in counter if counter[suit] >= 2}
        options = [card for card in player.hand if card.suit in suits]
        card1 = options[player.agent().choose(options, cost_event, f"请选择发动{self}的第一张手牌")]
        self.suits.remove(card1.suit)
        options.remove(card1)
        options = [card for card in options if card.suit == card1.suit]
        card2 = options[player.agent().choose(options, cost_event, f"请选择发动{self}的第二张手牌")]
        cards = [card1, card2]
        try:
            args = ctype.get_args(player, cards)
        except core.NoOptions:
            print(f"{player}想要发动技能{self}，但中途取消")
            return
        print(f"{player}发动了技能{self}，将{card1}、{card2}当{ctype.__name__}"
              f"对{'、'.join(str(target) for target in args)}使用")
        for card in cards:
            game.lose_card(player, card, "手", "使用", cost_event)
            game.table.append(card)
        ctype.effect(player, cards, args)


乱击 = 乱击v2


class 血裔(Skill):
    """
    主公技，锁定技，你的手牌上限+2X（X为其他群势力角色数）。
    """
    labels = {"主公技"}

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "calc_max_hand"

    def use(self, player, event, data=None):
        game = player.game
        n = len([p for p in game.iterate_live_players() if p is not player and p.faction == "群"])
        if n > 0:
            print(f"{player}的技能{self}被触发，手牌上限+{2 * n}")
        return data + 2 * n


class 双雄(Skill):
    """
    摸牌阶段，你可以放弃摸牌，改为进行一次判定，你获得此判定牌，且此回合你的每张与该判定牌不同颜色的手牌均可当【决斗】使用。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.suits = ""

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what in ["摸牌阶段", "turn_end"]:
            return True
        if event.what == "play":
            return player.cards("手", suits=self.suits) and C_("决斗").can_use(player, [])
        return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if event.what == "摸牌阶段":
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}")
                judgment = game.judge(player, use_skill_event)
                print(f"{player}获得了判定牌{judgment}")
                player.hand.append(judgment)
                game.table.remove(judgment)
                if judgment.suit in "♠♣":
                    self.suits = "♥♦"
                else:
                    self.suits = "♠♣"
                return 0
            else:
                return data
        elif event.what == "turn_end":
            self.suits = ""
            return
        # event.what == "play"
        ctype = C_("决斗")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards("手", suits=self.suits)
        card = options[player.agent().choose(options, cost_event, "请选择")]
        try:
            args = ctype.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要发动技能{self}，但中途取消")
            return
        game.lose_card(player, card, "手", "使用", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当{ctype.__name__}对{'、'.join(str(target) for target in args)}使用")
        ctype.effect(player, [card], args)


class 酒池(Skill):
    """
    你可以将一张♠手牌当【酒】使用。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player and player.cards("手", suits="♠")):
            return False
        return (event.what == "play" and C_("酒").can_use(player, []) or
                event.what == "card_asked" and issubclass(C_("酒"), event.args["card_type"]))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards("手", suits="♠")
        card = options[player.agent().choose(options, cost_event, "请选择")]
        game.lose_card(player, card, "手", "使用", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当酒使用")
        ctype = C_("酒")
        if event.what == "card_asked":
            return ctype, [card]
        else:  # event.what == "play"
            ctype.effect(player, [card], [])


class 肉林(Skill):
    """
    锁定技，你对女性角色使用的【杀】、女性角色对你使用的【杀】均需使用两张【闪】才能抵消。
    """

    def can_use(self, player, event):  # test_respond_disabled <- card_asked <- use_card
        if not (player is self.owner and event.what == "test_respond_disabled"):
            return False
        event0 = event.cause.cause
        return event0.what == "use_card" and issubclass(event0.card_type, C_("杀")) and \
               player in [event.who, event0.who] and event.who.male != event0.who.male

    def use(self, player, event, data=None):
        game = player.game
        print(f"{player}的技能{self}被触发")
        attacker, victim = event.cause.cause.who, event.who
        use_skill_event = UseSkillEvent(attacker, self, [victim], event)
        responded, _ = game.ask_for_response(victim, C_("闪"), use_skill_event, "请选择是否用闪来响应杀")
        return not responded


class 崩坏(Skill):
    """
    锁定技，结束阶段，若你不是体力值最小的角色，你失去1点体力或减1点体力上限。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_end"

    def use(self, player, event, data=None):
        game = player.game
        if player.hp == min(p.hp for p in game.iterate_live_players()):
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        print(f"{player}的技能{self}被触发")
        options = ["失去1点体力"]
        if player.is_wounded():
            options.append("减1点体力上限")
        choice = player.agent().choose(options, use_skill_event, "请选择")
        if choice:
            game.change_hp_cap(player, -1, use_skill_event)
        else:
            print(f"{player}失去了1点体力")
            game.lose_health(player, 1, use_skill_event)


class 暴虐(Skill):
    """
    主公技，当其他群势力角色造成伤害后，其可以进行判定，若结果为♠，你回复1点体力。
    """
    labels = {"主公技"}

    def can_use(self, player, event):
        return player is not self.owner and event.who is player and event.what == "造成伤害后" and player.faction == "群"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动{self.owner}的技能{self}"):
            return
        print(f"{player}发动了{self.owner}的技能{self}")
        judgment = game.judge(player, use_skill_event)
        if judgment.suit == "♠":
            game.recover(self.owner, 1, use_skill_event)


class 完杀(Skill):
    """
    锁定技，你的回合内，只有你和处于濒死状态的角色才能使用【桃】。
    """

    def can_use(self, player, event):  # test_respond_disabled <- card_asked <- dying
        game = player.game
        if not (player is self.owner and player is game.current_player()):
            return False
        if event.what == "dying":
            return True
        return event.what == "test_respond_disabled" and issubclass(C_("桃"), event.cause.args["card_type"]) \
               and event.who not in [player, event.cause.cause.who]

    def use(self, player, event, data=None):
        if event.what == "dying":
            print(f"{player}的技能{self}被触发，只有{player}和处于濒死状态的角色才能使用桃")
            return
        # event.what == "test_respond_disabled"
        return True


class 乱武(Skill):
    """
    限定技，出牌阶段，你可以令所有其他角色依次选择一项：1. 对距离最近的另一名角色使用【杀】；2. 失去1点体力。
    """
    labels = {"限定技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "play" and not self.used

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        print(f"{player}发动了技能{self}")
        ctype = C_("杀")
        for attacker in game.iterate_live_players():
            if attacker is player:
                continue
            attack_used = False
            min_dist = min(game.distance(attacker, p) for p in game.iterate_live_players() if p is not attacker)
            players = [p for p in game.iterate_live_players() if game.distance(attacker, p) == min_dist
                       and ctype.target_legal(attacker, p, [])]
            if players:
                ctype_provided, cards = game.ask_for_response(attacker, ctype, use_skill_event,
                                                              f"请选择是否响应{player}的技能{self}出杀", verb="使用")
                if ctype_provided:
                    victim = players[attacker.agent().choose(players, use_skill_event, f"请选择杀的目标")]
                    print(f"{attacker}对{victim}使用了{ctype_provided.__name__}")
                    ctype_provided.effect(attacker, cards, [victim])  # TODO: 方天画戟, 流离, 短兵
                    game.attack_quota += 1
                    attack_used = True
            if not attack_used:
                game.lose_health(attacker, 1, use_skill_event)
        self.used = True


class 帷幕(Skill):
    """
    锁定技，你不能成为黑色锦囊牌的目标。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "test_target_prohibited" and \
               issubclass(event.cause.card_type, (C_("锦囊牌"))) and core.color(event.cause.cards) == "black"

    def use(self, player, event, data=None):
        return True


class 猛进(Skill):
    """
    当你使用的【杀】被目标角色的【闪】抵消时，你可以弃置其一张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "attack_dodged" \
               and event.args["target"].total_cards()

    def use(self, player, event, data=None):
        game = player.game
        target = event.args["target"]
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if not player.agent().choose(["不发动", "发动"], event, f"请选择是否发动技能{self}"):
            return False
        place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择发动技能{self}弃置的{target}的牌")
        print(f"{player}发动了{self}，弃置了{target}的{place}{card}")
        game.lose_card(target, card, place[0], "弃置", use_skill_event)
        game.table.append(card)
        return False


class 化身(Skill):
    """
    游戏开始时，你随机获得两张未加入游戏的武将牌作为“化身”牌，然后亮出一张。你获得亮出“化身”牌的一个技能（你不可声明限定技、觉醒技或主公技），
    且性别与势力视为与“化身”牌相同。回合开始和结束后，你可以替换“化身”牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.repo = []
        self.current_skill = None

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        return event.what == "game_start" or \
               event.what in ["before_turn_start", "after_turn_end"] and event.who is player

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        print(f"{player}的技能{self}被触发")
        if event.what == "game_start":
            options = list(game.characters.values())
            for p in game.iterate_live_players():
                if p.character in options:
                    options.remove(p.character)
            self.repo = random.sample(options, 2)
            print(f"{player}获得了两张{self}牌")
        if self.current_skill:
            print(f"{player}失去了技能{self.current_skill}")
            player.skills = player.skills[:]
            player.skills.remove(self.current_skill)
            for mark in player.marks:
                if mark.startswith("化身") and player.marks[mark] > 0:
                    game.change_mark(player, mark, -1, event)
        ch = self.repo[player.agent().choose(self.repo, use_skill_event, f"请选择发动技能{self}亮出的武将牌")]
        print(f"{player}亮出了{self}牌{ch.name}，性别变为{'男' if ch.male else '女'}，势力变为{ch.faction}")
        player.male = ch.male
        player.faction = ch.faction
        options = [sk for sk in ch.skills if not sk.labels & {"限定技", "觉醒技", "主公技"}]
        if options:
            new_skill = options[player.agent().choose(options, use_skill_event, f"请选择一项技能")](player)
            print(f"{player}获得了技能{new_skill}")
            self.current_skill = new_skill
            player.skills = player.skills[:]
            player.skills.append(new_skill)
            game.change_mark(player, f"化身：{new_skill}", 1, event)
        else:
            self.current_skill = None


class 新生(Skill):
    """
    当你受到1点伤害后，你可以获得一张新的“化身”牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.化身 = None

    def can_use(self, player, event):  # 受到伤害后 <- damage
        if player is not self.owner:
            return False
        return event.what == "game_start" or event.what == "受到伤害后" and event.who is player and self.化身

    def use(self, player, event, data=None):
        if event.what == "game_start":
            for skill in player.skills:
                if isinstance(skill, 化身):
                    self.化身 = skill
                    break
            else:
                self.化身 = 化身(player)
            return
        game = player.game
        n = event.cause.n
        use_skill_event = UseSkillEvent(player, self, [], event)
        for _ in range(n):
            if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}，获得了一张新的“化身”牌")
                options = list(game.characters.values())
                for p in game.iterate_live_players():
                    if p.character in options:
                        options.remove(p.character)
                for ch in self.化身.repo:
                    if ch in options:
                        options.remove(ch)
                self.化身.repo.append(random.choice(options))


class 雷击(Skill):
    """
    当你使用或打出【闪】时，你可以令一名其他角色进行判定，若结果为♠，你对该角色造成2点雷电伤害。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "respond" \
               and issubclass(event.args["card_type"], C_("闪"))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        players = [p for p in game.iterate_live_players() if p is not player]
        target = players[player.agent().choose(players, use_skill_event, f"请选择发动技能{self}的目标角色")]
        print(f"{player}对{target}发动了技能{self}")
        judgment = game.judge(player, use_skill_event)
        if judgment.suit == "♠":
            game.damage(target, 2, player, use_skill_event, "雷")


class 鬼道(Skill):
    """
    在一名角色的判定牌生效前，你可以打出一张黑色牌替换之。
    """

    def can_use(self, player, event):
        return player is self.owner and event.what == "judge" and player.cards(suits="♠♣")

    def use(self, player, event, data=None):
        game = player.game
        judgment = data
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return judgment
        options = player.cards(suits="♠♣", return_places=True)
        place, card = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}打出的牌")]
        print(f"{player}发动了技能{self}，将判定牌改为{card}，并获得了{judgment}")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        game.lose_card(player, card, place[0], "打出", cost_event)
        player.hand.append(judgment)  # Game.judge will add judge result to the table
        return card


class 黄天(Skill):
    """
    主公技，其他群势力角色的每个出牌阶段限一次，该角色可以交给你一张【闪】或【闪电】。
    """
    labels = {"主公技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is not self.owner and player.faction == "群" and event.who is player):
            return False
        return (event.what == "turn_start" or
                event.what == "play" and self.use_quota > 0 and player.cards(types=(C_("闪"), C_("闪电"))))

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self, [self.owner])
        options = player.cards(types=(C_("闪"), C_("闪电")))
        card = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}给出的手牌")]
        print(f"{player}发动了{self.owner}的技能{self}，将{card}交给了{self.owner}")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        game.lose_card(player, card, "手", "获得", cost_event)
        self.owner.hand.append(card)
        self.use_quota -= 1


class 蛊惑(Skill):
    """
    你可以扣置一张手牌当任意一张基本牌或普通锦囊牌使用或打出。其他角色可以进行质疑并翻开此牌：
    若为假则此牌作废，且质疑者摸一张牌；
    若为真则质疑者失去1点体力。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what in ["play", "card_asked"] and player.hand

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        card = player.hand[player.agent().choose(player.hand, cost_event, "请选择")]
        if event.what == "card_asked":
            ctype = event.args["card_type"]
            verb = event.args["verb"]
            args = []
            print(f"{player}发动了技能{self}，扣置了一张手牌当{ctype.__name__}{verb}")
        else:  # event.what == "play"
            options = ["杀", "火杀", "雷杀", "闪", "桃", "酒", "无懈可击", "南蛮入侵", "五谷丰登", "桃园结义", "万箭齐发",
                       "过河拆桥", "顺手牵羊", "无中生有", "决斗", "借刀杀人", "铁索连环", "火攻"]
            options = [card_name for card_name in options if C_(card_name).can_use(player, [])]
            if not options:
                return
            card_name = options[player.agent().choose(options, use_skill_event, "请选择一种基本牌或即时锦囊")]
            ctype = C_(card_name)
            verb = "使用"
            try:
                args = ctype.get_args(player, [])
            except core.NoOptions:
                print(f"{player}想要发动技能{self}，但中途取消")
                return
            print(f"{player}发动了技能{self}，"
                  f"扣置了一张手牌当{ctype.__name__}对{'、'.join(str(target) for target in args)}使用")
        game.lose_card(player, card, "手", verb, cost_event)
        success = True
        for p in game.iterate_live_players():
            if p is player:
                continue
            if p.agent().choose(["不质疑", "质疑"], use_skill_event, f"请选择是否质疑{player}"):
                print(f"{p}对{player}表示质疑，翻开了{player}扣置的手牌{card}")
                if card.type == ctype:
                    game.lose_health(p, 1, use_skill_event)
                else:
                    success = False
                    game.deal_cards(p, 1)
                break
        else:
            print(f"{player}翻开了扣置的手牌{card}")
        game.table.append(card)
        if event.what == "card_asked":
            if success:
                return ctype, [card]
            else:
                return game.ask_for_response(player, ctype, event.cause, "请重新选择", verb)
                # TODO: Now 八卦阵 will judge again if not success
        else:  # event.what == "play"
            if success:
                ctype.effect(player, [card], args)


class 悲歌(Skill):
    """
    当一名角色受到【杀】造成的伤害后，你可以弃置一张牌，然后令其进行判定，若结果为：
    ♥，其回复1点体力；
    ♦，其摸两张牌；
    ♣，伤害来源弃置两张牌；
    ♠，伤害来源翻面。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.what == "受到伤害后"):
            return False
        event0 = event.cause.cause  # 受到伤害后 <- damage <- use_card
        return event0.what == "use_card" and issubclass(event0.card_type, C_("杀")) and player.total_cards() > 0

    def use(self, player, event, data=None):
        game = player.game
        target = event.who
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动{self}"):
            return
        print(f"{player}发动了技能{self}")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        player.discard_n_cards(1, cost_event)
        judgment = game.judge(target, use_skill_event)
        suit = judgment.suit
        if suit == "♥":
            game.recover(target, 1, use_skill_event)
            return
        elif suit == "♦":
            game.deal_cards(target, 2)
            return
        inflicter = event.cause.who
        if not inflicter.is_alive():
            return
        if suit == "♠":
            game.flip(inflicter)
        else:  # suit == "♣":
            inflicter.discard_n_cards(2, use_skill_event)


class 断肠(Skill):
    """
    锁定技，当你死亡时，杀死你的角色失去所有武将技能。
    """

    def can_use(self, player, event):  # die <- damage
        if not (player is self.owner and event.who is player and event.what == "die" and event.cause.what == "damage"):
            return False
        inflicter = event.cause.who
        return inflicter and inflicter.is_alive() and inflicter is not player

    def use(self, player, event, data=None):
        game = player.game
        target = event.cause.who
        print(f"{player}的技能{self}被触发，{target}失去了所有武将技能")
        target.skills = []
        use_skill_event = UseSkillEvent(player, self, [], event)
        game.change_mark(target, "断肠", 1, use_skill_event)


class 武神(Skill):
    """
    锁定技，你的♥手牌视为【杀】；你使用♥【杀】无距离限制。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "test_use_prohibited":
            cards = event.args["cards"]
            return len(cards) == 1 and cards[0].suit == "♥" and not issubclass(event.args["card_type"], C_("杀"))
        elif event.what == "modify_use_range":
            cards = event.args["cards"]
            return len(cards) == 1 and cards[0].suit == "♥" and issubclass(event.args["card_type"], C_("杀"))
        if not player.cards("手", suits="♥"):
            return False
        return (event.what == "play" and C_("杀").can_use(player, []) or
                event.what == "card_asked" and issubclass(C_("杀"), event.args["card_type"]))

    # TODO: prohibit using ♥ cards for response

    def use(self, player, event, data=None):
        if event.what == "test_use_prohibited":
            return True
        elif event.what == "modify_use_range":
            return None
        # event.what == "play"
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards("手", suits="♥")
        card = options[player.agent().choose(options, cost_event, "请选择")]
        ctype = C_("杀")
        if event.what == "card_asked":
            game.lose_card(player, card, "手", "打出", cost_event)
            game.table.append(card)
            print(f"{player}发动了技能{self}，将{card}当杀打出")
            return ctype, [card]
        # event.what == "play"
        try:
            if not ctype.can_use(player, [card]):
                raise core.NoOptions
            args = ctype.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要使用杀，但中途取消")
            return
        game.lose_card(player, card, "手", "使用", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当杀对{'、'.join(str(target) for target in args)}使用")
        ctype.effect(player, [card], args)


class 武魂(Skill):
    """
    锁定技，当你受到1点伤害后，你令伤害来源获得1个“梦魇”标记；
    当你死亡时，你令拥有最多“梦魇”标记的一名其他角色进行判定：若结果不为【桃】或【桃园结义】，该角色死亡。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        return player is self.owner and event.who is player and event.what in ["受到伤害后", "die"]

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "受到伤害后":  # 受到伤害后 <- damage
            inflicter = event.cause.who
            if inflicter and inflicter is not player:
                game.change_mark(inflicter, "梦魇", event.cause.n, use_skill_event)
            return
        # event.what == "die"
        if event.cause.what == "damage":
            # Due to accounting ordering, the 受到伤害后 event will not be triggered for the final blow
            inflicter = event.cause.who
            if inflicter and inflicter is not player:
                game.change_mark(inflicter, "梦魇", event.cause.n, use_skill_event)
        max_mark = max(p.marks["梦魇"] for p in game.iterate_live_players())
        if max_mark == 0:
            return
        options = [p for p in game.iterate_live_players() if p.marks["梦魇"] == max_mark]
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的对象")]
        print(f"{player}对{target}发动了技能{self}")
        judgment = game.judge(target, use_skill_event)
        if not issubclass(judgment.type, (C_("桃"), C_("桃园结义"))):
            game.kill_player(target, use_skill_event)
        for p in game.iterate_live_players():
            n = p.marks["梦魇"]
            game.change_mark(p, "梦魇", -n, use_skill_event)


class 涉猎(Skill):
    """
    摸牌阶段，你可以改为亮出牌堆顶的五张牌，然后获得其中每种花色的牌各一张。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "摸牌阶段"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not game.autocast and not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        cards = [game.draw_from_deck() for _ in range(5)]
        print(f"{player}发动了技能{self}，亮出了牌堆顶的五张牌{'、'.join(str(c) for c in cards)}")
        options = cards[:]
        to_keep = []
        while options:
            card = options[player.agent().choose(options, use_skill_event, f"请选择下一张要获得的牌")]
            to_keep.append(card)
            options = [c for c in options if c.suit != card.suit]
        to_discard = [c for c in cards if c not in to_keep]
        player.hand.extend(to_keep)
        game.table.extend(to_discard)
        print(f"{player}获得了{'、'.join(str(c) for c in to_keep)}")
        print(f"{'、'.join(str(c) for c in to_discard)}被弃置")
        return 0


class 攻心(Skill):
    """
    出牌阶段限一次，你可以观看一名其他角色的手牌，然后你可以展示其中一张♥牌，选择一项：1. 弃置此牌；2. 将此牌置于牌堆顶。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p.hand and p is not player]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and self.legal_targets(player)

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        # event.what == play
        use_skill_event = UseSkillEvent(player, self)
        players = self.legal_targets(player)
        target = players[player.agent().choose(players, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}对{target}发动了技能{self}")
        use_skill_event.targets = [target]
        game.view_cards(player, target.hand, use_skill_event)
        self.use_quota -= 1
        options = target.cards("手", suits="♥")
        if not options:
            return
        options = [None] + options
        card = options[player.agent().choose(options, use_skill_event, f"请选择{target}的一张♥手牌")]
        if not card:
            return
        print(f"{player}展示了{target}的手牌{card}")
        choice = player.agent().choose(["弃置", "置于牌堆顶"], use_skill_event, f"请选择如何处置{target}的手牌{card}")
        if choice:  # 置于牌堆顶
            print(f"{player}将{target}的手牌{card}置于牌堆顶")
            game.deck.append(card)
            verb = "置入"
        else:  # 弃置
            print(f"{player}弃置了{target}的手牌{card}")
            game.discard([card])
            verb = "弃置"
        game.lose_card(target, card, "手", verb, use_skill_event)


class 琴音(Skill):
    """
    弃牌阶段结束时，若你于此阶段内弃置过你的至少两张手牌，则你可以选择一项：1. 令所有角色各回复1点体力；2. 令所有角色各失去1点体力。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "弃牌阶段"

    def use(self, player, event, data=None):
        if len(data) < 2:
            return data
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        choice = player.agent().choose(["不发动", "令所有角色各回复1点体力", "令所有角色各失去1点体力"], use_skill_event,
                                       f"请选择是否发动技能{self}")
        if choice == 1:  # 令所有角色各回复1点体力
            print(f"{player}发动了技能{self}，令所有角色各回复1点体力")
            for p in game.iterate_live_players():
                game.recover(p, 1, use_skill_event)
        elif choice == 2:  # 令所有角色各失去1点体力
            print(f"{player}发动了技能{self}，令所有角色各失去1点体力")
            for p in game.iterate_live_players():
                game.lose_health(p, 1, use_skill_event)
        return data


class 业炎(Skill):
    """
    限定技，出牌阶段，你可以选择至多三名角色，对这些角色造成共计至多3点火焰伤害，
    若你将对一名角色分配2点或更多火焰伤害，你须先弃置四张花色各不相同的手牌并失去3点体力。
    """
    labels = {"限定技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "play" and not self.used

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        players = [p for p in game.iterate_live_players()]
        target = players[player.agent().choose(players, use_skill_event, f"请选择发动技能{self}造成第1点伤害的目标")]
        targets = [target]
        can_bomb = (len({c.suit for c in player.hand}) == 4)  # Only repeat target if player has 4 suits in hand
        if not can_bomb:
            players.remove(target)
        for i in range(2, 4):
            options = [None] + players
            target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}造成第{i}点伤害的目标")]
            if target is None:
                break
            targets.append(target)
            if not can_bomb:
                players.remove(target)
        use_skill_event.targets = targets
        bomb = (len(targets) != len(set(targets)))  # Some targets are repeated
        if bomb:
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            to_discard = []
            for suit in "♠♥♣♦":
                cards = player.cards("手", suits=suit)
                card = cards[player.agent().choose(cards, cost_event, f"请选择发动技能{self}弃置的{suit}手牌")]
                to_discard.append(card)
            print(f"{player}弃置了手牌{'、'.join(str(c) for c in to_discard)}并失去了3点体力，"
                  f"对{'、'.join(str(p) for p in set(targets))}发动了技能{self}")
            for card in to_discard:
                game.lose_card(player, card, "手", "弃置", cost_event)
            game.discard(to_discard)
            game.lose_health(player, 3, cost_event)
        else:
            print(f"{player}对{'、'.join(str(p) for p in set(targets))}发动了技能{self}")
        damage_counter = {}
        for target in targets:
            if target in damage_counter:
                damage_counter[target] += 1
            else:
                damage_counter[target] = 1
        for p in game.iterate_live_players():
            if p in damage_counter:
                game.damage(p, damage_counter[p], player, use_skill_event, "火")
        self.used = True


class 七星(Skill):
    """
    游戏开始时，你将牌堆顶的七张牌扣置于你的武将牌上，称为“星”，然后你可以用任意张手牌替换等量的“星”；
    摸牌阶段结束时，你可以用任意张手牌替换等量的“星”。
    """

    def can_use(self, player, event):
        game = player.game
        if player is not self.owner:
            return False
        if event.what == "game_start":
            return True
        elif event.what == "test_skip_phase":  # 摸牌阶段结束时 ~ 出牌阶段开始时
            return event.who is player and event.args["phase"] == "出牌阶段" and "摸牌阶段" not in game.skipped \
                   and player.repo and player.hand
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        print(f"{player}的技能{self}被触发")
        if event.what == "game_start":
            player.repo = [game.draw_from_deck() for _ in range(7)]
            player.show_repo = False
        # “游戏开始时”的第二部分，以及“摸牌阶段结束时”
        options = player.repo[:]
        n = min(len(options), len(player.hand))
        stars = [options[i] for i in
                 player.agent().choose_many(options, (0, n), use_skill_event, "请选择要替换的“星”（多选）")]
        n = len(stars)
        options = player.cards("手")
        if n == 0:
            return
        elif n == len(options):
            hand_cards = options
        else:
            hand_cards = [options[i] for i in player.agent().choose_many(options, n, use_skill_event, "请选择要替换的手牌")]
        print(f"{player}用{n}张手牌替换了等量的“星”")
        for card in hand_cards:
            game.lose_card(player, card, "手", "置于", use_skill_event)
        for card in stars:
            player.repo.remove(card)
        player.repo.extend(hand_cards)
        player.hand.extend(stars)


class 狂风(Skill):
    """
    结束阶段，你可以移去一张“星”并选择一名角色，然后直到你的下回合开始之前，当该角色受到火焰伤害时，此伤害+1。
    """

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        return (event.what == "turn_start" and event.who is player
                or event.what == "turn_end" and event.who is player and len(player.repo) > 0
                or event.what == "受到伤害时" and event.who.marks["狂风"] > 0 and event.cause.type == "火")

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "turn_start":
            for p in game.iterate_live_players():
                if p.marks["狂风"] > 0:
                    game.change_mark(p, "狂风", -1, use_skill_event)
            return
        elif event.what == "turn_end":
            options = [None] + player.repo
            star = options[player.agent().choose(options, use_skill_event, f"请选择是否移去一张“星”来发动技能{self}")]
            if not star:
                return
            options = [p for p in game.iterate_live_players()]
            target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
            print(f"{player}移去了一张“星”（{star}），对{target}发动了技能{self}")
            player.repo.remove(star)
            game.discard([star])
            game.change_mark(target, "狂风", 1, use_skill_event)
            return
        else:  # event.what == "受到伤害时"
            print(f"{player}的技能{self}被触发，{event.who}受到的火属性伤害+1")
            return data + 1


class 大雾(Skill):
    """
    结束阶段，你可以移去任意张“星”并选择等量的角色，然后直到你的下回合开始之前，当这些角色受到非雷电伤害时，防止此伤害。
    """

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        return (event.what == "turn_start" and event.who is player
                or event.what == "turn_end" and event.who is player and len(player.repo) > 0
                or event.what == "受到伤害时" and event.who.marks["大雾"] > 0 and event.cause.type != "雷")

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "turn_start":
            for p in game.iterate_live_players():
                if p.marks["大雾"] > 0:
                    game.change_mark(p, "大雾", -1, use_skill_event)
            return
        elif event.what == "turn_end":
            options = [p for p in game.iterate_live_players()]
            n = min(len(options), len(player.repo))
            targets = [options[i] for i in
                       player.agent().choose_many(options, (0, n), use_skill_event, f"请选择发动技能{self}的目标（多选）")]
            n = len(targets)
            options = player.repo[:]
            if n == 0:
                return
            elif n == len(options):
                stars = options
            else:
                stars = [options[i] for i in player.agent().choose_many(options, n, use_skill_event, "请选择要弃置的“星”")]
            print(f"{player}移去了{len(stars)}张“星”（{'、'.join(str(c) for c in stars)}），"
                  f"对{'、'.join(str(p) for p in targets)}发动了技能{self}")
            for target in targets:
                game.change_mark(target, "大雾", 1, use_skill_event)
            for card in stars:
                player.repo.remove(card)
            game.discard(stars)
            return
        else:  # event.what == "受到伤害时"
            print(f"{player}的技能{self}被触发，防止了{event.who}受到的伤害")
            return 0


class 归心(Skill):
    """
    当你受到1点伤害后，你可以依次获得每名其他角色所属区域里的一张牌，然后你翻面。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        return player is self.owner and event.who is player and event.what == "受到伤害后"

    def use(self, player, event, data=None):
        game = player.game
        n = event.cause.n
        use_skill_event = UseSkillEvent(player, self, [], event)
        players = [p for p in game.iterate_live_players() if p is not player]
        for _ in range(n):
            if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}")
                for target in players:
                    if target.total_cards("手装判") == 0:
                        continue
                    place, card = game.pick_card(player, target, "手装判", use_skill_event,
                                                 f"请选择发动技能{self}从{target}所属区域里获得的一张牌")
                    if place[0] == "手":
                        print(f"{player}获得了{target}的一张手牌")
                    else:
                        print(f"{player}获得了{target}{place}{card}")
                    game.lose_card(target, card, place[0], "获得", use_skill_event)
                    player.hand.append(card)
                game.flip(player)
            else:
                break


class 飞影(Skill):
    """
    锁定技，其他角色计算与你的距离+1。
    """

    def can_use(self, player, event):
        return player is self.owner and event.what == "calc_distance" and event.args["to"] is player

    def use(self, player, event, data=None):
        return data + 1


class 狂暴(Skill):
    """
    锁定技，游戏开始时，你获得2个“暴怒”标记；当你造成或受到1点伤害后，你获得1个“暴怒”标记。
    """

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        return event.what == "game_start" or event.what in ["造成伤害后", "受到伤害后"] and event.who is player

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "game_start":
            n = 2
        else:  # event.what in ["造成伤害后", "受到伤害后"]
            n = event.cause.n  # 造成伤害后/受到伤害后 <- damage
        print(f"{player}的技能{self}被触发")
        game.change_mark(player, "暴怒", n, use_skill_event)


class 无谋(Skill):
    """
    锁定技，当你使用普通锦囊牌时，你弃1个“暴怒”或失去1点体力。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        elif event.what == "use_card":
            return issubclass(event.card_type, C_("即时锦囊"))
        elif event.what == "respond":
            return issubclass(event.args["card_type"], C_("即时锦囊"))
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        print(f"{player}的技能{self}被触发")
        options = ["失去1点体力"]
        if player.marks["暴怒"] > 0:
            options += ["弃1个“暴怒”标记"]
        choice = player.agent().choose(options, cost_event, "请选择")
        if choice:
            game.change_mark(player, "暴怒", -1, cost_event)
        else:
            game.lose_health(player, 1, cost_event)


class 无前(Skill):
    """
    出牌阶段，你可以弃2个“暴怒”并选择一名其他角色，然后本回合你获得“无双”且该角色的防具失效。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.victims = set()
        self.无双 = 无双(owner)

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p is not player and p not in self.victims]

    def can_use(self, player, event):
        if not player is self.owner:
            return False
        if event.what == "play":
            return event.who is player and player.marks["暴怒"] >= 2 and self.legal_targets(player)
        elif event.what == "test_armor_disabled":
            return event.who in self.victims
        elif event.what == "turn_end":
            return event.who is player and self.无双 in player.skills
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "test_armor_disabled":
            return True
        elif event.what == "turn_end":
            self.victims.clear()
            print(f"{player}失去了技能{self.无双}")
            new_skills = player.skills[:]
            new_skills.remove(self.无双)
            player.skills = new_skills
            return
        # event.what == "play"
        game = player.game
        use_skill_event = UseSkillEvent(player, self)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
        use_skill_event.targets = [target]
        print(f"{player}对{target}发动了技能{self}")
        game.change_mark(player, "暴怒", -2, cost_event)
        use_skill_event.targets = [target]
        self.victims.add(target)
        if self.无双 not in player.skills:
            print(f"{player}获得了技能{self.无双}")
            player.skills = player.skills[:] + [self.无双]


class 神愤(Skill):
    """
    出牌阶段限一次，你可以弃6个“暴怒”，然后对所有其他角色各造成1点伤害，其他角色弃置装备区里的所有牌，然后弃置四张手牌，最后你翻面。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 0

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and player.marks["暴怒"] >= 6

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        print(f"{player}发动了技能{self}")
        game.change_mark(player, "暴怒", -6, cost_event)
        for target in game.iterate_live_players():
            if target is player:
                continue
            game.damage(target, 1, player, use_skill_event)
        for target in game.iterate_live_players():
            if target is player:
                continue
            equips = target.cards("装")
            if equips:
                print(f"{target}弃置了装备区里的牌{'、'.join(str(c) for c in equips)}")
                for card in equips:
                    game.lose_card(target, card, "装", "弃置", use_skill_event)
                game.discard(equips)
            target.discard_n_cards(4, use_skill_event)
        game.flip(player)
        self.use_quota -= 1


class 绝境v1(Skill):
    """
    锁定技，你的手牌上限+2；当你进入或脱离濒死状态时，你摸一张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what in ["calc_max_hand", "dying", "saved"]

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "calc_max_hand":
            print(f"{player}的技能{self}被触发，手牌上限+2")
            return data + 2
        print(f"{player}的技能{self}被触发")
        game.deal_cards(player, 1)

    def __str__(self):
        return "绝境"


class 绝境v2(Skill):
    """
    锁定技，你的回合外，当你的手牌数小于2时，你将手牌补至2张。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player and len(player.hand) < 2):
            return False
        return (event.what == "lose_card" and event.zone == "手" and player.game.current_player() is not player
                or event.what == "after_turn_end")

    def use(self, player, event, data=None):
        game = player.game
        print(f"{player}的技能{self}被触发")
        n = 2 - len(player.hand)
        game.deal_cards(player, n)

    def __str__(self):
        return "绝境"


绝境 = 绝境v2


class 龙魂(Skill):
    """
    你可以将一张牌按下列规则使用或打出：♥当【桃】；♦当火【杀】；♣当【闪】；♠当【无懈可击】。
    """

    def can_use(self, player, event):
        if player is not self.owner or event.who is not player:
            return False
        if event.what == "play":
            return (C_("火杀").can_use(player, []) and player.cards(suits="♦")
                    or C_("桃").can_use(player, []) and player.cards(suits="♥"))
        elif event.what == "card_asked":
            ctype = event.args["card_type"]
            return (issubclass(C_("桃"), ctype) and player.cards(suits="♥") or
                    issubclass(C_("火杀"), ctype) and player.cards(suits="♦") or
                    issubclass(C_("闪"), ctype) and player.cards(suits="♣") or
                    issubclass(C_("无懈可击"), ctype) and player.cards(suits="♠"))
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        if event.what == "card_asked":
            ctype = event.args["card_type"]
            if issubclass(C_("桃"), ctype):
                suit, card_name = "♥", "桃"
            elif issubclass(C_("火杀"), ctype):
                suit, card_name = "♦", "火杀"
            elif issubclass(C_("闪"), ctype):
                suit, card_name = "♣", "闪"
            else:  # issubclass(C_("无懈可击"), ctype)
                suit, card_name = "♠", "无懈可击"
            options = player.cards(suits=suit, return_places=True)
            place, card = options[player.agent().choose(options, cost_event, "请选择")]
            print(f"{player}发动了技能{self}，将{place}{card}当{card_name}打出")
            game.lose_card(player, card, place[0], "打出", cost_event)
            game.table.append(card)
            return C_(card_name), [card]
        # event.what == "play"
        suits = ""
        if C_("火杀").can_use(player, []):
            suits += "♦"
        if C_("桃").can_use(player, []):
            suits += "♥"
        options = player.cards(suits=suits, return_places=True)
        place, card = options[player.agent().choose(options, cost_event, "请选择")]
        zone = place[0]
        if card.suit == "♥":  # 桃
            game.lose_card(player, card, zone, "使用", cost_event)
            game.table.append(card)
            print(f"{player}发动了技能{self}，将{card}当桃使用")
            C_("桃").effect(player, [card], [player])
            return
        # 火杀
        key = None
        if zone == "装":
            for k, val in player.装备区.items():
                if val is card:
                    key = k
                    break
        player.remove_card(card)  # remove_card before get_args to avoid cases when using the card for 武圣 will make
        # the attack invalid (e.g. target becomes out of range, player no longer has attack quota (诸葛连弩), or the
        # number of targets is changed (方天画戟))
        ctype = C_("火杀")
        try:
            if not ctype.can_use(player, [card]):
                raise core.NoOptions
            args = ctype.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要使用杀，但中途取消")
            if zone == "手":
                player.hand.append(card)
            else:
                player.装备区[key] = card
            return
        if zone == "手":
            player.hand.append(card)
        else:
            player.装备区[key] = card
        game.lose_card(player, card, zone, "使用", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当火杀对{'、'.join(str(target) for target in args)}使用")
        ctype.effect(player, [card], args)


class 连破(Skill):
    """
    当你杀死一名角色后，你可于此回合结束后获得一个额外回合。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.n_kills = 0

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "die":
            return event.cause.what == "damage" and event.cause.who is player
        elif event.what == "after_turn_end":
            return self.n_kills > 0
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.n_kills = 0
            return
        if event.what == "die":  # die <- damage
            self.n_kills += 1
            return
        # event.what == after_turn_end
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            old_pid = game.current_pid
            game.current_pid = player.pid()
            game.run_turn()
            game.current_pid = old_pid


class 忍戒(Skill):
    """
    锁定技，当你受到伤害后或于弃牌阶段内弃置手牌后，你获得X个“忍”标记（X为伤害值或弃置的手牌数）。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        return player is self.owner and event.who is player and event.what in ["受到伤害后", "弃牌阶段"]

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "受到伤害后":
            n = event.cause.n
        else:  # event.what == "弃牌阶段":
            n = len(data)
        game.change_mark(player, "忍", n, use_skill_event)
        return data


class 拜印(Skill):
    """
    觉醒技，准备阶段，若“忍”的数量大于3，你减1点体力上限，然后获得“极略”。
    """
    labels = {"觉醒技"}

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "before_turn_start" \
               and player.marks["忍"] > 3

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        print(f"{player}的技能{self}被触发，减了1点体力上限，并获得了技能“极略”")
        game.change_hp_cap(player, -1, use_skill_event)
        player.skills = player.skills[:]  # Avoid modifying the list when iterating through it in Game.trigger_skills()
        player.skills.remove(self)
        player.skills.append(极略(player))
        game.trigger_skills(Event(player, "wake"))


class 极略(Skill):
    """
    你可以弃置1个“忍”，发动下列一项技能：“鬼才”、“放逐”、“集智”、“制衡”或“完杀”。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.鬼才 = 鬼才(owner)
        self.放逐 = 放逐(owner)
        self.集智 = 集智(owner)
        self.制衡 = 制衡(owner)
        self.完杀 = 完杀(owner)

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what in ["turn_start", "turn_end"]:  # Resetting 制衡 and 完杀 don't need marks
            return event.who is player
        if player.marks["忍"] <= 0:
            return False
        for skill in [self.鬼才, self.放逐, self.集智]:
            if skill.can_use(player, event):
                return True
        return event.what == "play" and event.who is player \
               and (self.制衡.can_use(player, event) or self.完杀 not in player.skills)

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.制衡.use_quota = 1
            return
        elif event.what == "turn_end":
            if self.完杀 in player.skills:
                print(f"{player}失去了技能{self.完杀}")
                new_skills = player.skills[:]
                new_skills.remove(self.完杀)
                player.skills = new_skills
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what != "play" and \
                not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        print(f"{player}发动了技能{self}")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        game.change_mark(player, "忍", -1, cost_event)
        if event.what == "judge":
            return self.鬼才.use(player, event, data)
        elif event.what == "受到伤害后":
            return self.放逐.use(player, event, data)
        elif event.what in ["use_card", "respond"]:
            return self.集智.use(player, event, data)
        # event.what == "play"
        options = []
        if self.制衡.can_use(player, event):
            options.append("制衡")
        if self.完杀 not in player.skills:
            options.append("完杀")
        choice = options[player.agent().choose(options, use_skill_event, "请选择要发动的技能")]
        if choice == "制衡":
            return self.制衡.use(player, event, data)
        # choice == "完杀"
        print(f"{player}获得了技能{self.完杀}")
        player.skills = player.skills[:] + [self.完杀]


## ======= 其他官方 =======
# ======= 蜀 =======
class 淑慎(Skill):
    """
    当你回复1点体力后，你可以令一名其他角色摸一张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "recover"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        n = data
        options = [p for p in game.iterate_live_players() if p is not player]
        for _ in range(n):
            if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                break
            target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
            print(f"{player}对{target}发动了技能{self}")
            game.deal_cards(target, 1)
        return n


class 神智(Skill):
    """
    准备阶段开始时，若你已受伤且你的手牌数不小于你的体力值，你可以弃置所有手牌，然后回复1点体力。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_start" and \
               player.is_wounded() and player.total_cards("手") >= player.hp

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            game.discard_all_cards(player, "手", cost_event)
            game.recover(player, 1, use_skill_event)


class 无言(Skill):
    """
    锁定技，你使用的非延迟类锦囊对其他角色无效；其他角色使用的非延迟类锦囊对你无效。
    """

    def can_use(self, player, event):  # test_card_nullify(player) <- use_card(user, card_type)
        if not (player is self.owner and event.what == "test_card_nullify"):
            return False
        event0 = event.cause
        return issubclass(event0.card_type, C_("即时锦囊")) and \
               (event0.who is player and event.who is not player or event0.who is not player and event.who is player)

    def use(self, player, event, data=None):
        event0 = event.cause
        print(f"{player}的技能{self}被触发，{event0.who}使用的{event0.card_type.__name__}对{event.who}无效")
        return True


class 举荐(Skill):
    """
    出牌阶段限一次，你可以弃置任意张牌，然后令一名其他角色摸等量的牌。若你以此法弃牌不少于三张且均为同一类别，你回复1点体力。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and player.total_cards() > 0

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        options = [p for p in game.iterate_live_players() if p is not player]
        target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
        use_skill_event.targets = [target]
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(return_places=True)
        place_card_tuples = [options[i] for i in
                             player.agent().choose_many(options, (1, len(options)), cost_event, "请选择要弃置的牌")]
        print(f"{player}对{target}发动了技能{self}，弃置了{'、'.join(str(card) for _, card in place_card_tuples)}")
        for place, card in place_card_tuples:
            game.lose_card(player, card, place[0], "弃置", cost_event)
            game.table.append(card)
        n = len(place_card_tuples)
        game.deal_cards(target, n)
        if n >= 3 and len({card.type.class_ for _, card in place_card_tuples}) == 1:
            game.recover(player, 1, use_skill_event)
        self.use_quota -= 1


class 生息(Skill):
    """
    弃牌阶段开始时，若你此回合内未造成过伤害，你可以摸两张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.cool = True

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "造成伤害后":
            return True
        elif event.what == "phase_start":
            return event.args["phase"] == "弃牌阶段" and self.cool
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.cool = True
        elif event.what == "造成伤害后":
            self.cool = False
        else:  # event.what == "phase_start"
            game = player.game
            use_skill_event = UseSkillEvent(player, self, cause=event)
            if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}")
                game.deal_cards(player, 2)


class 守成(Skill):
    """
    当一名与你势力相同的角色在其回合外失去最后的手牌后，你可以令该角色摸一张牌。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.what == "lose_card" and event.zone == "手"):
            return False
        target = event.who
        return target.faction == player.faction and player.game.current_player() is not target and not target.hand and target.is_alive()

    def use(self, player, event, data=None):
        game = player.game
        target = event.who
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}对{target}发动了技能{self}")
            game.deal_cards(target, 1)


class 潜袭(Skill):
    """
    每当你使用【杀】对距离为1的目标角色造成伤害时，若其已受伤且体力上限大于2，你可以防止此伤害，改为令其减1点体力上限。
    """

    def can_use(self, player, event):  # 造成伤害时 <- damage <- use_card
        if not (player is self.owner and event.who is player and event.what == "造成伤害时"):
            return False
        target = event.cause.whom
        event0 = event.cause.cause
        return event0.who is player and event0.what == "use_card" and issubclass(event0.card_type, C_("杀")) \
               and player.game.distance(player, target) == 1 and target.is_wounded() and target.hp_cap > 2

    def use(self, player, event, data=None):
        game = player.game
        target = event.cause.whom
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否对{target}发动技能{self}"):
            return data
        print(f"{player}对{target}发动了技能{self}，防止伤害，改为令{target}减1点体力上限")
        game.change_hp_cap(target, -1, use_skill_event)
        return 0


class 蒺藜(Skill):
    """
    当你于一回合内使用或打出第X张牌时，你可以摸X张牌（X为你的攻击范围）。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.counter = 0

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        return event.what == "turn_start" or event.who is player and event.what in ["use_card", "respond"]

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.counter = 0
            return
        self.counter += 1
        if self.counter != player.attack_range():
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            player.game.deal_cards(player, self.counter)


class 心战(Skill):
    """
    出牌阶段限一次，你可以观看牌堆顶的三张牌，然后展示其中任意数量的♥牌并获得之，其余以任意顺序置于牌堆顶。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        print(f"{player}发动了技能{self}，观看了牌堆顶的3张牌")
        cards = [game.draw_from_deck() for _ in range(3)]
        game.view_cards(player, cards, use_skill_event)
        hearts = [card for card in cards if card.suit == "♥"]
        to_take = [hearts[i] for i in
                   player.agent().choose_many(hearts, (0, len(hearts)), use_skill_event, "请选择要获得的♥牌")]
        cards = [card for card in cards if card not in to_take]
        if len(to_take) > 0:
            print(f"{player}展示并获得了{'、'.join(str(c) for c in to_take)}")
            player.hand.extend(to_take)
        if len(cards) > 0:
            cards = [cards[i] for i in
                     player.agent().choose_many(cards, len(cards), use_skill_event, "请排列放置于牌堆顶的牌")]
            print(f"{player}将{len(cards)}张牌放回了牌堆顶")
            game.deck = game.deck + cards[::-1]
        self.use_quota -= 1


class 制蛮(Skill):
    """
    当你对其他角色造成伤害时，你可以防止此伤害，然后你获得其装备区或判定区里的一张牌。
    """

    def can_use(self, player, event):  # 造成伤害时 <- damage
        return player is self.owner and event.who is player and event.what == "造成伤害时" and \
               event.cause.whom is not player

    def use(self, player, event, data=None):
        game = player.game
        target = event.cause.whom
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否对{target}发动技能{self}"):
            print(f"{player}发动了技能{self}，防止了对{target}造成伤害")
            place, card = game.pick_card(player, target, "装判", use_skill_event, "请选择要获得的一张牌")
            if card:
                print(f"{player}获得了{target}{place}{card}")
                game.lose_card(target, card, place[0], "获得", use_skill_event)
                player.hand.append(card)
            return 0
        return data


class 恩怨(Skill):
    """
    锁定技，当其他角色对你使用【桃】时，该角色摸一张牌；当你受到其他角色的伤害后，该角色需交给你一张手牌，否则失去1点体力。
    """

    def can_use(self, player, event):
        if not player is self.owner:
            return False
        if event.what == "respond":  # respond(savior, card_type, cards) <- dying(player)
            return event.who is not player and event.args["card_type"] == C_("桃") and event.cause.who is player
        elif event.what == "受到伤害后":  # 受到伤害后(player) <- damage(inflicter, player)
            inflicter = event.cause.who
            return event.who is player and inflicter is not None and inflicter is not player and inflicter.is_alive()
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        print(f"{player}的技能{self}被触发")
        if event.what == "respond":
            game.deal_cards(event.who, 1)
        else:  # event.what == "受到伤害后"
            inflicter = event.cause.who
            options = [None] + inflicter.cards("手")
            card = options[inflicter.agent().choose(options, use_skill_event, f"请选择将一张手牌交给{player}，或失去1点体力")]
            if not card:
                print(f"{inflicter}失去了1点体力")
                game.lose_health(inflicter, 1, use_skill_event)
            else:
                print(f"{inflicter}将一张手牌交给了{player}")
                game.lose_card(inflicter, card, "手", "获得", use_skill_event)
                player.hand.append(card)


class 眩惑(Skill):
    """
    出牌阶段限一次，你可以将一张手牌交给一名其他角色，然后获得该角色区域的一张牌，然后你可以将这张牌交给任意一名角色。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and player.hand

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = [p for p in game.iterate_live_players() if p is not player]
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标角色")]
        card_to_give = player.hand[player.agent().choose(player.hand, cost_event, f"请选择交给{target}的手牌")]
        print(f"{player}发动了技能{self}，将一张手牌交给了{target}")
        game.lose_card(player, card_to_give, "手", "获得", cost_event)
        target.hand.append(card_to_give)
        place, card_taken = game.pick_card(player, target, "手装判", use_skill_event, f"请选择从{target}处获得的牌")
        if place[0] == "手":
            print(f"{player}获得了{target}的一张手牌")
        else:
            print(f"{player}获得了{target}{place}{card_taken}")
        game.lose_card(target, card_taken, place[0], "获得", use_skill_event)
        options = [p for p in game.iterate_live_players()]
        target2 = options[player.agent().choose(options, use_skill_event, f"请选择将获得的牌{card_taken}转交给哪名角色")]
        print(f"{player}将获得的牌交给了{target2}")
        target2.hand.append(card_taken)
        self.use_quota -= 1


class 父魂(Skill):
    """
    摸牌阶段，你可以放弃摸牌，改为亮出牌堆顶的两张牌并获得之，若：
    1. 亮出的牌中包含红色牌，你获得技能“武圣”直到回合结束；
    2. 亮出的牌中包含黑色牌，你需弃一张牌，然后获得技能“咆哮”，直到回合结束。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.武圣 = 武圣(owner)
        self.咆哮 = 咆哮(owner)

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what in ["摸牌阶段", "turn_end"]

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if event.what == "摸牌阶段":
            if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                return data
            cards = [game.draw_from_deck() for _ in range(2)]
            print(f"{player}发动了技能{self}，亮出并获得了牌堆顶的牌{cards[0]}、{cards[1]}")
            player.hand.extend(cards)
            if core.color(cards) != "black":  # 包含红色牌
                print(f"{player}获得了技能{self.武圣}")
                player.skills = player.skills[:] + [self.武圣]
            if core.color(cards) != "red":  # 包含黑色牌
                print(f"{player}获得了技能{self.咆哮}")
                player.skills = player.skills[:] + [self.咆哮]
                cost_event = Event(player, "use_skill_cost", use_skill_event)
                player.discard_n_cards(1, cost_event)
            return 0
        # event.what == "turn_end"
        new_skills = player.skills[:]
        for skill in [self.武圣, self.咆哮]:
            if skill in player.skills:
                print(f"{player}失去了技能{skill}")
                new_skills.remove(skill)
        player.skills = new_skills


class 当先(Skill):
    """
    锁定技，回合开始时，你执行一个额外的出牌阶段。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_start"

    def use(self, player, event, data=None):
        game = player.game
        print(f"{player}的技能{self}被触发，执行一个额外的出牌阶段")
        game.出牌阶段()
        game.attack_quota = 1
        game.drink_quota = 1


class 伏枥(Skill):
    """
    限定技，当你处于濒死状态时，你可以将体力回复至X点（X为全场势力数）。若如此做，你翻面。
    """
    labels = {"限定技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "dying" and \
               not self.used and player.hp <= 0

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        print(f"{player}发动了技能{self}")
        n_factions = len({p.faction for p in game.iterate_live_players()})
        n = n_factions - player.hp
        game.recover(player, n, use_skill_event)
        game.flip(player, use_skill_event)
        self.used = True


class 龙吟(Skill):
    """
    一名角色于其出牌阶段内使用【杀】时，你可以弃置一张牌，令此【杀】不计入出牌阶段的使用次数，然后若此【杀】为红色，你摸一张牌。
    """

    def can_use(self, player, event):
        game = player.game
        return player is self.owner and event.what == "use_card" \
               and event.who is game.current_player() and issubclass(event.card_type, C_("杀")) and player.cards()

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        print(f"{player}发动了技能{self}")
        player.discard_n_cards(1, cost_event)
        game.attack_quota += 1
        if core.color(event.cards) == "red":
            game.deal_cards(player, 1)


class 巧说(Skill):
    """
    出牌阶段限一次，你可以与一名角色拼点：若你赢，本回合你使用普通锦囊牌无距离限制且可以多选择或少选择一个目标；若你没赢，本回合你不能使用锦囊牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = None

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p is not player and p.hand]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "play":
            return not self.buff and len(player.hand) > 0 and self.legal_targets(player)
        elif event.what == "modify_use_range":
            return self.buff == "good" and issubclass(event.args["card_type"], C_("即时锦囊"))
        elif event.what == "confirm_targets":
            return self.buff == "good" and issubclass(event.cause.card_type, C_("即时锦囊"))
        elif event.what == "test_use_prohibited":
            return self.buff == "bad" and issubclass(event.args["card_type"], C_("即时锦囊"))
        elif event.what == "turn_end":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "play":
            options = self.legal_targets(player)
            target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
            print(f"{player}对{target}发动了技能{self}")
            use_skill_event.targets = [target]
            winner, _, _ = game.拼点(player, target, use_skill_event)
            if winner is player:
                self.buff = "good"
            else:
                self.buff = "bad"
            return
        elif event.what == "modify_use_range":
            return None
        elif event.what == "confirm_targets":  # confirm_targets <- use_card
            ctype = event.cause.card_type
            if ctype.n_targets is None:  # minus 1 target
                if data and player.agent().choose(["不发动", "发动"], use_skill_event,
                                                  f"请选择是否发动技能{self}为{ctype.__name__}减少一个目标"):
                    target = data[player.agent().choose(data, use_skill_event, "请选择减少的目标")]
                    print(f"{player}发动了技能{self}，为{ctype.__name__}去掉了一个目标角色{target}")
                    data.remove(target)
            else:  # add 1 target
                cards = event.cause.cards
                if issubclass(ctype, C_("无中生有")):
                    options = [p for p in game.iterate_live_players() if p is not player]
                else:
                    options = [p for p in game.iterate_live_players()
                               if p not in data and ctype.target_legal(player, p, cards)]
                if options and player.agent().choose(["不发动", "发动"], use_skill_event,
                                                     f"请选择是否发动技能{self}为{ctype.__name__}增加一个目标"):
                    target = options[player.agent().choose(options, use_skill_event, "请选择增加的目标")]
                    print(f"{player}发动了技能{self}，为{ctype.__name__}指定了额外的目标角色{target}")
                    data.append(target)
            return data
        elif event.what == "test_use_prohibited":
            return True
        else:  # event.what == "turn_end"
            self.buff = None
            return


class 纵适(Skill):
    """
    当你拼点后，若你赢，你可以获得对手拼点的牌；若你没赢，你可以获得你拼点的牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.what == "拼点后" and player in [event.who, event.args["whom"]]

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            winner, card1, card2 = event.args["result"]
            if event.who is player:
                opponent, card_player, card_opponent = event.args["whom"], card1, card2
            else:
                opponent, card_player, card_opponent = event.who, card2, card1
            if winner is player:
                owner, card = opponent, card_opponent
            else:
                owner, card = player, card_player
            print(f"{player}发动了技能{self}，获得了{owner}拼点的牌{card}")
            game.table.remove(card)
            player.hand.append(card)


class 陷嗣(Skill):
    """
    准备阶段，你可以选择至多两名角色，将这些角色的各一张牌置于武将牌上，称为“逆”；
    一名角色需要对你使用【杀】时，其可以移去两张“逆”，视为对你使用【杀】。
    """

    def can_use(self, player, event):
        if event.what == "turn_start":
            return player is self.owner and event.who is player
        elif event.what == "play":
            ctype = C_("杀")
            return player is not self.owner and event.who is player and len(self.owner.repo) >= 2 and \
                   ctype.can_use(player, []) and ctype.target_legal(player, self.owner, [])
        else:  # TODO: 借刀杀人, 乱武
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if event.what == "turn_start":
            options = [p for p in game.iterate_live_players() if p.total_cards() > 0]
            if not options or not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                return
            targets = [options[i] for i in player.agent().choose_many(options, (1, 2), use_skill_event, f"请选择目标角色")]
            print(f"{player}对{'、'.join(str(p) for p in targets)}发动了技能{self}")
            for target in targets:
                place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择{target}的一张牌作为“逆”")
                print(f"{player}将{target}{place}{card}置于武将牌上作为“逆”")
                game.lose_card(target, card, place[0], "置于", use_skill_event)
                player.repo.append(card)
            return
        # event.what == "play"
        options = self.owner.repo
        cards = [options[i] for i in player.agent().choose_many(options, 2, use_skill_event, "请选择要弃置的“逆”")]
        print(f"{player}发动了{self.owner}的技能{self}，移去了两张“逆”（{'、'.join(str(c) for c in cards)}），"
              f"视为对{self.owner}使用杀")
        for card in cards:
            self.owner.repo.remove(card)
        game.table.extend(cards)
        C_("杀").effect(player, [], [self.owner])


class 奔袭(Skill):
    """
    锁定技，当你于回合内使用牌时，本回合你计算与其他角色的距离-1；
    你的回合内，若你与所有其他角色的距离均为1，则你无视其他角色的防具且你使用【杀】可以多指定一个目标。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.counter = 0

    def buff(self, player):
        game = player.game
        if player is not game.current_player():
            return False
        for p in game.iterate_live_players():
            if game.distance(player, p) > 1:
                return False
        return True

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        game = player.game
        if event.what == "turn_start":
            return event.who is player
        elif event.what == "use_card":
            return event.who is player and game.current_player() is player
        elif event.what == "calc_distance":
            return event.who is player and self.counter > 0 and game.current_player() is player
        elif event.what == "test_armor_disabled":
            return event.who is not player and self.buff(player)
        elif event.what == "modify_n_targets":
            return event.who is player and issubclass(event.args["card_type"], C_("杀")) and self.buff(player)
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.counter = 0
            return
        elif event.what == "use_card":
            self.counter += 1
            print(f"{player}的技能{self}被触发，{player}与其他角色的距离减1（累计减{self.counter}）")
            return
        elif event.what == "calc_distance":
            return data - self.counter
        elif event.what == "test_armor_disabled":
            print(f"{player}的技能{self}被触发，无视了{event.who}的防具")
            return True
        else:  # event.what == "modify_n_targets"
            print(f"{player}的技能{self}被触发，使用【杀】可以多指定一个目标")
            return data + 1


class 强识(Skill):
    """
    出牌阶段开始时，你可以展示一名其他角色的一张手牌，然后本回合当你使用与展示的牌类别相同的牌时，你可以摸一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.card_class = None

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "phase_start":
            return event.args["phase"] == "出牌阶段"
        elif event.what == "use_card":
            return self.card_class and issubclass(event.card_type, self.card_class)
        elif event.what == "turn_end":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], cause=event)
        if event.what == "use_card":
            if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}")
                game.deal_cards(player, 1)
            return
        elif event.what == "turn_end":
            self.card_class = None
            return
        # event.what == phase_start
        options = [p for p in game.iterate_live_players() if p is not player and p.hand]
        if not options or not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        target = options[player.agent().choose(options, use_skill_event, f"请选择目标角色")]
        card = random.choice(target.hand)
        print(f"{player}发动了技能{self}，展示了{target}的手牌{card}")
        self.card_class = C_(card.type.class_)


class 献图(Skill):
    """
    其他角色的出牌阶段开始时，你可以摸两张牌，然后将两张牌交给该角色。此阶段结束时，若其没有杀死过角色，则你失去1点体力。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.cool = True

    def can_use(self, player, event):
        if player is not self.owner or event.who is player:
            return False
        game = player.game
        if event.what == "phase_start":
            return event.args["phase"] == "出牌阶段"
        elif event.what == "die":
            return not self.cool and event.cause.what == "damage" and event.cause.who is game.current_player()
        elif event.what == "turn_end":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        if not player.is_alive():
            return data
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        if event.what == "die":
            self.cool = True
            return
        elif event.what == "turn_end":
            if not self.cool:
                print(f"{player}的技能{self}被触发，{player}失去1点体力")
                game.lose_health(player, 1, cost_event)
            self.cool = True
            return
        # event.what == "phase_start":
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        print(f"{player}发动了技能{self}")
        self.cool = False
        game.deal_cards(player, 2)
        target = game.current_player()
        options = player.cards(return_places=True)
        place_card_tuples = [options[i] for i in
                             player.agent().choose_many(options, 2, cost_event, f"请选择交给{target}的两张牌")]
        hand_cards = [card for place, card in place_card_tuples if place[0] == "手"]
        equip_cards = [card for place, card in place_card_tuples if place[0] == "装"]
        if hand_cards:
            print(f"{player}把{len(hand_cards)}张手牌交给了{target}")
        if equip_cards:
            print(f"{player}把装备区的牌{'、'.join(str(c) for c in equip_cards)}交给了{target}")
        for place, card in place_card_tuples:
            game.lose_card(player, card, place[0], "获得", cost_event)
            target.hand.append(card)


class 忠勇(Skill):
    """
    当你使用【杀】后，你可以将此【杀】或目标角色使用的【闪】交给另一名其他角色，若其获得的牌为红色，则其可以对你攻击范围内的角色使用一张【杀】。
    """
    # TODO: 忠勇


class 樵拾(Skill):
    """
    其他角色的结束阶段，若其手牌数等于你，你可以与其各摸一张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is not player and \
               event.what == "turn_end" and len(player.hand) == len(event.who.hand)

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        print(f"{player}发动了技能{self}")
        game.deal_cards(player, 1)
        game.deal_cards(event.who, 1)


class 燕语(Skill):
    """
    出牌阶段，你可以重铸【杀】；出牌阶段结束时，若你于此阶段内重铸过两张或更多的【杀】，则你可以令一名其他角色摸两张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_count = 0

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "play":
            return player.cards(types=C_("杀"))
        elif event.what == "turn_end":
            return self.use_count >= 2
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if event.what == "turn_start":
            self.use_count = 0
        elif event.what == "play":
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            options = player.cards(types=C_("杀"))
            card = options[player.agent().choose(options, cost_event, "请选择要重铸的杀")]
            print(f"{player}发动了技能{self}，重铸了手牌{card}")
            game.lose_card(player, card, "手", "重铸", cost_event)
            game.table.append(card)
            game.deal_cards(player, 1)
            self.use_count += 1
        else:  # event.what == "turn_end"
            if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}令一名其他角色摸两张牌"):
                return
            players = [p for p in game.iterate_live_players() if p is not player]
            target = players[player.agent().choose(players, use_skill_event, "请选择目标角色")]
            print(f"{player}对{target}发动了技能{self}")
            game.deal_cards(target, 2)


class 抚戎(Skill):
    """
    出牌阶段限一次，你可以和一名其他角色同时展示一张手牌：
    若你展示的是【杀】且该角色不是【闪】，你弃置此【杀】，然后对其造成1点伤害；
    若你展示的不是【杀】且该角色是【闪】，你弃置此牌，然后获得其一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p is not player and p.hand]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "turn_start" or
                event.what == "play" and self.use_quota > 0 and player.hand and self.legal_targets(player))

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self)
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}对{target}发动了技能{self}")
        self.use_quota -= 1
        use_skill_event.targets = [target]
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        card1 = player.hand[player.agent().choose(player.hand, use_skill_event, "请选择要展示的手牌")]
        card2 = target.hand[target.agent().choose(target.hand, use_skill_event, "请选择要展示的手牌")]
        print(f"{player}展示了手牌{card1}，{target}展示了手牌{card2}")
        attack = issubclass(card1.type, C_("杀"))
        dodge = issubclass(card2.type, C_("闪"))
        if attack and not dodge:
            print(f"{player}弃置了手牌{card1}")
            game.lose_card(player, card1, "手", "弃置", cost_event)
            game.table.append(card1)
            game.damage(target, 1, player, use_skill_event)
        elif not attack and dodge:
            print(f"{player}弃置了手牌{card1}")
            game.lose_card(player, card1, "手", "弃置", cost_event)
            game.table.append(card1)
            place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择要获得的{target}的牌")
            if place[0] == "手":
                print(f"{player}获得了{target}的一张手牌")
            else:
                print(f"{player}获得了{target}{place}{card}")
            game.lose_card(target, card, place[0], "获得", use_skill_event)
            player.hand.append(card)


class 豹变(Skill):
    """
    锁定技，若你的体力值：不大于3，你拥有技能“挑衅”；不大于2，你拥有技能“咆哮”；为1，你拥有技能“神速”。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.挑衅 = 挑衅(owner)
        self.咆哮 = 咆哮(owner)
        self.神速 = 神速(owner)

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        if player.hp <= 3 and self.挑衅.can_use(player, event):
            return True
        if player.hp <= 2 and self.咆哮.can_use(player, event):
            return True
        if player.hp == 1 and self.神速.can_use(player, event):
            return True
        return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.挑衅.use_quota = 1
            return
        elif event.what == "play":
            return self.挑衅.use(player, event, data)
        elif event.what in ["test_attack_quota", "use_card"]:
            return self.咆哮.use(player, event, data)
        elif event.what in ["test_skip_phase", "modify_use_range"]:
            return self.神速.use(player, event, data)
        else:
            raise ValueError(f"event.what == {event.what}")


# ======= 魏 =======
class 骁果(Skill):
    """
    其他角色的结束阶段开始时，你可以弃置一张基本牌。若如此做，除非该角色弃置一张装备牌，否则受到你造成的1点伤害。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is not player and event.what == "turn_end"

    def use(self, player, event, data=None):
        cards = player.cards("手", types=C_("基本牌"))
        if not cards:
            return data
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        card = cards[player.agent().choose(cards, cost_event, f"请选择发动技能{self}弃置的基本牌")]
        print(f"{player}发动了技能{self}，弃置了{card}")
        game.lose_card(player, card, "手", "弃置", cost_event)
        game.discard([card])
        target = event.who
        options = target.cards(types=C_("装备牌"), return_places=True)
        if not options or not target.agent().choose(["不弃置", "弃置"], use_skill_event, f"请选择是否弃置一张装备牌"):
            game.damage(target, 1, player, use_skill_event)
        else:
            place, card = options[target.agent().choose(options, use_skill_event, "请选择要弃置的装备牌")]
            print(f"{target}弃置了{place}{card}")
            game.lose_card(target, card, place[0], "弃置", use_skill_event)
            game.discard([card])


class 恂恂(Skill):
    """
    摸牌阶段开始时，你可以观看牌堆顶的四张牌，将其中两张牌以任意顺序置于牌堆顶，其余以任意顺序置于牌堆底。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "摸牌阶段"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not game.autocast and not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        print(f"{player}发动了技能{self}，观看了牌堆顶的4张牌")
        cards = [game.draw_from_deck() for _ in range(4)]
        top_cards = [cards[i] for i in
                     player.agent().choose_many(cards, 2, use_skill_event, "请选择并排列放置于牌堆顶的2张牌")]
        for card in top_cards:
            cards.remove(card)
        cards = [cards[i] for i in
                 player.agent().choose_many(cards, 2, use_skill_event, "请排列放置于牌堆底的牌")]
        game.deck = cards[::-1] + game.deck + top_cards[::-1]
        print(f"{player}将2张牌放回了牌堆顶，将2张牌放回了牌堆底")
        return data


class 忘隙(Skill):
    """
    当你对其他角色造成1点伤害后，或受到其他角色造成的1点伤害后，你可以与该角色各摸一张牌。
    """

    def can_use(self, player, event):  # 造成伤害后/受到伤害后 <- damage
        if not (player is self.owner and event.who is player and event.what in ["造成伤害后", "受到伤害后"]):
            return False
        inflicter = event.cause.who
        return inflicter is not None

    def use(self, player, event, data=None):
        game = player.game
        damage_event = event.cause
        if event.what == "造成伤害后":
            other = damage_event.whom
        else:  # event.what == "受到伤害后"
            other = damage_event.who
        if other is player or not other.is_alive():
            return
        use_skill_event = UseSkillEvent(player, self, [other], event)
        for _ in range(damage_event.n):
            if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                break
            print(f"{player}发动了技能{self}")
            game.deal_cards(player, 1)
            game.deal_cards(other, 1)


class 援护(Skill):
    """
    结束阶段，你可将一张装备牌置入一名角色的装备区里，然后根据此牌的副类别执行以下效果：
    武器牌，你弃置该角色距离为1的一名角色区域里的一张牌；
    防具牌，该角色摸一张牌；
    坐骑牌，该角色回复1点体力。
    """

    def legal_targets(self, player, card):
        game = player.game
        return [p for p in game.iterate_live_players() if card.type.equip_type not in p.装备区]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player and event.what == "turn_end"):
            return False
        cards = player.cards(types=C_("装备牌"))
        if not cards:
            return False
        for card in cards:
            if self.legal_targets(player, card):
                return True
        return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(types=C_("装备牌"), return_places=True)
        place, card = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的装备牌")]
        options = self.legal_targets(player, card)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}发动了技能{self}，将{card}放入了{target}的装备区")
        game.lose_card(player, card, place[0], "置入", cost_event)
        equip_type = card.type.equip_type
        target.装备区[equip_type] = card
        if equip_type == "武器":
            options = [p for p in game.iterate_live_players() if game.distance(target, p) == 1]
            if options:
                target2 = options[player.agent().choose(options, use_skill_event, "请选择一名角色，弃置其区域的一张牌")]
                place, card = game.pick_card(player, target2, "手装判", use_skill_event, "请选择要弃置的牌")
                if card:
                    print(f"{player}弃置了{target2}的{place}{card}")
                    game.lose_card(target2, card, place[0], "弃置", use_skill_event)
                    game.discard([card])
        elif equip_type == "防具":
            game.deal_cards(target, 1)
        elif equip_type in ["-1坐骑", "+1坐骑"]:
            game.recover(target, 1, use_skill_event)


class 奇策(Skill):
    """
    出牌阶段限一次，你可以将所有手牌当任意一张普通锦囊牌使用。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and len(player.hand) > 0

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        options = ["过河拆桥", "顺手牵羊", "无中生有", "决斗", "借刀杀人",
                   "南蛮入侵", "五谷丰登", "桃园结义", "万箭齐发", "铁索连环", "火攻"]
        options = [card_name for card_name in options if C_(card_name).can_use(player, player.hand)]
        if not options:
            return
        use_skill_event = UseSkillEvent(player, self)
        card_name = options[player.agent().choose(options, use_skill_event, "请选择一种即时锦囊")]
        ctype = C_(card_name)
        cards = player.cards("手")
        try:
            args = ctype.get_args(player, cards)
        except core.NoOptions:
            print(f"{player}想要发动技能{self}，但中途取消")
            return
        print(f"{player}发动了技能{self}，将{'、'.join(str(card) for card in cards)}当{ctype.__name__}"
              f"对{'、'.join(str(target) for target in args)}使用")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        for card in cards:
            game.lose_card(player, card, "手", "使用", cause=cost_event)
            game.table.append(card)
        ctype.effect(player, cards, args)
        self.use_quota -= 1


class 智愚(Skill):
    """
    当你受到伤害后，你可以摸一张牌，然后展示所有手牌，若颜色均相同，伤害来源弃置一张手牌。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        return player is self.owner and event.who is player and event.what == "受到伤害后"

    def use(self, player, event, data=None):
        game = player.game
        inflicter = event.cause.who
        use_skill_event = UseSkillEvent(player, self, [inflicter], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            game.deal_cards(player, 1)
            print(f"{player}展示了手牌{'、'.join(str(card) for card in player.hand)}")
            if inflicter is None or core.color(player.hand) == "no_color" or not inflicter.hand:
                return
            hand = inflicter.hand
            discard_event = Event(inflicter, "discard", use_skill_event)
            card = hand[inflicter.agent().choose(hand, discard_event, "请选择弃置的牌")]
            print(f"{inflicter}弃置了手牌{card}")
            game.lose_card(inflicter, card, "手", "弃置", discard_event)
            game.discard([card])


class 横江(Skill):
    """
    每当你受到1点伤害后， 你可以令当前回合角色本回合手牌上限-1。然后若该角色于本回合的弃牌阶段内没有弃置牌，你于回合结束时摸一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.n = 0
        self.draw = False

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "受到伤害后":
            return event.who is player
        elif event.what == "calc_max_hand":
            return self.n > 0
        elif event.what == "弃牌阶段":
            return self.n > 0
        elif event.what == "turn_end":
            return self.draw
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "turn_start":
            self.n = 0
            self.draw = False
            return
        elif event.what == "受到伤害后":  # 受到伤害后 <- damage
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}的发动了技能{self}")
                self.n += event.cause.n
            return
        elif event.what == "calc_max_hand":
            print(f"{player}的技能{self}被触发，令{event.who}的手牌上限减{self.n}")
            return data - self.n
        elif event.what == "弃牌阶段":
            if len(data) == 0:
                self.draw = True
            return data
        else:  # event.what == "turn_end"
            print(f"{player}的技能{self}被触发")
            game.deal_cards(player, 1)
            return


class 毅重(Skill):
    """
    锁定技，当你没装备防具时，黑色的【杀】对你无效。
    """

    def can_use(self, player, event):  # test_card_nullify <- use_card
        return (player is self.owner and "防具" not in player.装备区
                and event.who is player and event.what == "test_card_nullify"
                and issubclass(event.cause.card_type, C_("杀")) and core.color(event.cause.cards) == "black")

    def use(self, player, event, data=None):
        print(f"{player}的技能{self}被触发，黑杀无效")
        return True


class 落英(Skill):
    """
    其他角色的♣牌因弃置或判定而放入弃牌堆后，你可以选择其中的任意张获得之。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is not player):
            return False
        if event.what == "lose_card":
            return event.type == "弃置" and event.cause.what != "弃牌阶段" and event.card.suit == "♣"
        elif event.what == "弃牌阶段":
            return True
        # TODO: 判定

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        owner = event.who
        if event.what == "lose_card":
            if not (game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}")):
                return
            card = event.card
            # print(f"{player}发动了技能{self}，获得了{owner}弃置的{card}")
            # game.table.remove(card)
            # player.hand.append(card)
            # TODO: 弃置
            return
        # event.what == "弃牌阶段"
        cards = [c for c in data if c.suit == "♣"]
        if not cards:
            return data
        if not (game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}")):
            return data
        to_keep = [cards[i] for i in player.agent().choose_many(cards, (1, len(cards)), use_skill_event, "请选择获得的牌")]
        print(f"{player}发动了技能{self}，获得了{owner}弃置的{'、'.join(str(c) for c in to_keep)}")
        data = [c for c in data if c not in to_keep]
        player.hand.extend(to_keep)
        return data


class 酒诗(Skill):
    """
    若你的武将牌正面向上，你可以翻面，视为使用一张【酒】；若你的武将牌背面向上，你受到伤害后可以翻面。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = False

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        ctype = C_("酒")
        if event.what == "play":
            return ctype.can_use(player, []) and not player.flipped
        elif event.what == "card_asked":
            return issubclass(ctype, event.args["card_type"]) and not player.flipped
        elif event.what == "受到伤害时":
            return True
        elif event.what == "受到伤害后":
            return self.buff
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if event.what == "受到伤害时":
            self.buff = player.flipped
            return data
        elif event.what == "受到伤害后":
            if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}")
                game.flip(player, use_skill_event)
            self.buff = False
            return data
        print(f"{player}发动了技能{self}，视为使用一张酒")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        game.flip(player, cost_event)
        ctype = C_("酒")
        if event.what == "card_asked":
            return ctype, []
        else:  # event.what == "play"
            ctype.effect(player, [], [])


class 绝情(Skill):
    """
    锁定技，你即将造成的伤害视为失去体力。
    """

    def can_use(self, player, event):  # 造成伤害时 <- damage
        return player is self.owner and event.who is player and event.what == "造成伤害时" and \
               event.cause.whom is not player

    def use(self, player, event, data=None):
        game = player.game
        target = event.cause.whom
        n = event.cause.n
        use_skill_event = UseSkillEvent(player, self, [target], event)
        print(f"{player}的技能{self}被触发，{target}失去了{n}点体力")
        game.lose_health(target, n, use_skill_event)
        return 0


class 伤逝(Skill):
    """
    当你的手牌数小于X时，你可以将手牌摸至X张（X为你已损失的体力值）。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player and len(player.hand) < player.hp_cap - player.hp):
            return False
        if event.what == "lose_card":
            return event.zone == "手" and event.cause != "弃牌阶段"
        elif event.what in ["lose_health", "change_hp_cap"]:
            return True
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            n = (player.hp_cap - player.hp) - len(player.hand)
            game.deal_cards(player, n)


class 权计(Skill):
    """
    当你受到1点伤害后，你可以摸一张牌，然后将一张手牌置于武将牌上，称为“权”；你的手牌上限+X（X为“权”的数量）。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what in ["受到伤害后", "calc_max_hand"]

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "calc_max_hand":
            n = len(player.repo)
            if n > 0:
                print(f"{player}的技能{self}被触发，手牌上限+{n}")
            return data + n
        # event.what == "受到伤害后"
        n = event.cause.n  # 受到伤害后 <- damage
        use_skill_event = UseSkillEvent(player, self, [], event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        for _ in range(n):
            if not (game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}")):
                return
            print(f"{player}发动了技能{self}")
            game.deal_cards(player, 1)
            options = player.hand
            card = options[player.agent().choose(options, cost_event, f"请选择一张手牌置于武将牌上")]
            print(f"{player}将{card}置于武将牌上作为“权”")
            game.lose_card(player, card, "手", "置入", cost_event)
            player.repo.append(card)


class 自立(Skill):
    """
    觉醒技，准备阶段，若“权”的数量不小于3，你选择一项：回复1点体力；或摸两张牌。然后你减1点体力上限，获得“排异”。
    """
    labels = {"觉醒技"}

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "before_turn_start" \
               and len(player.repo) >= 3

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, event)
        print(f"{player}的技能{self}被触发，减了1点体力上限，并获得了技能“排异”")
        game.change_hp_cap(player, -1, use_skill_event)
        options = ["摸两张牌"]
        if player.is_wounded():
            options.append("回复1点体力")
        if player.agent().choose(options, use_skill_event, f"请选择"):
            game.recover(player, 1, use_skill_event)
        else:
            game.deal_cards(player, 2)
        player.skills = player.skills[:]  # Avoid modifying the list when iterating through it in Game.trigger_skills()
        player.skills.remove(self)
        new_skill = 排异(player)
        # new_skill.use(player, event, data)  # This skill will not be iterated this time, so call it explicitly
        player.skills.append(new_skill)
        game.trigger_skills(Event(player, "wake"))


class 排异(Skill):
    """
    出牌阶段限一次，你可以将一张“权”放入弃牌堆并令一名角色摸两张牌。若该角色的手牌多于你，则你对其造成1点伤害。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and player.repo

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.repo
        card = options[player.agent().choose(options, cost_event, f"请选择用来发动技能{self}一张“权”")]
        options = [p for p in game.iterate_live_players()]
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}发动了技能{self}，弃置了一张“权”（{card}），并令{target}摸了两张牌")
        use_skill_event.targets = [target]
        player.repo.remove(card)
        game.table.append(card)
        game.deal_cards(target, 2)
        if len(target.hand) > len(player.hand):
            game.damage(target, 1, player, use_skill_event)
        self.use_quota -= 1


class 将驰(Skill):
    """
    摸牌阶段，你可以选择一项：
    1. 多摸一张牌，然后本回合你不能使用或打出【杀】；
    2. 少摸一张牌，然后本回合你使用【杀】无距离限制且可以多使用一张【杀】。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = None

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what in ["摸牌阶段", "turn_end"]:
            return True
        elif event.what == "modify_use_range":
            return self.buff == "good" and issubclass(event.args["card_type"], C_("杀"))
        elif event.what == "test_use_prohibited":
            return self.buff == "bad" and issubclass(event.args["card_type"], C_("杀"))
        elif event.what == "test_respond_disabled":  # test_respond_disabled <- card_asked
            return self.buff == "bad" and issubclass(event.cause.args["card_type"], C_("杀"))
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if event.what == "摸牌阶段":
            choice = player.agent().choose(["不发动", "多摸一张牌", "少摸一张牌"], use_skill_event, f"请选择是否发动技能{self}")
            if choice == 1:
                print(f"{player}发动了技能{self}，多摸了一张牌")
                self.buff = "bad"
                return data + 1
            elif choice == 2:
                print(f"{player}发动了技能{self}，少摸了一张牌")
                self.buff = "good"
                game.attack_quota += 1
                return data - 1
            else:  # 不发动
                return data
        elif event.what == "modify_use_range":
            return None
        elif event.what in ["test_use_prohibited", "test_respond_disabled"]:
            return True
        else:  # event.what == "turn_end":
            self.buff = None
            return


class 贞烈(Skill):
    """
    当你成为其他角色【杀】或普通锦囊牌的目标后，你可以失去1点体力令此牌对你无效，然后你弃置其一张牌。
    """

    def can_use(self, player, event):  # test_card_nullify(player) <- use_card(user, card_type)
        return player is self.owner and event.who is player and event.what == "test_card_nullify" and \
               issubclass(event.cause.card_type, (C_("杀"), C_("即时锦囊"))) and event.cause.who is not player

    def use(self, player, event, data=None):
        if data:
            return data
        game = player.game
        target = event.cause.who
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}，失去了1点体力，令{event.cause.card_type.__name__}对其无效")
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            game.lose_health(player, 1, cost_event)
            if player.is_alive():
                place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择要弃置的{target}的牌")
                if card:
                    print(f"{player}弃置了{target}{place}{card}")
                    game.lose_card(target, card, place[0], "弃置", use_skill_event)
                    game.table.append(card)
            return True
        return data


class 秘计(Skill):
    """
    结束阶段，你可以摸X张牌（X为你已损失的体力值），然后你可以将等量的手牌交给其他角色。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_end" and player.is_wounded()

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            n = player.hp_cap - player.hp
            game.deal_cards(player, n)
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}将{n}张手牌交给其他角色"):
                options = player.cards("手")
                cards = [options[i] for i in player.agent().choose_many(options, n, "请选择要交给其他角色的手牌")]
                options = [p for p in game.iterate_live_players() if p is not player]
                target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
                print(f"{player}将{n}张手牌交给了{target}")
                for card in cards:
                    game.lose_card(player, card, "手", "获得", use_skill_event)
                target.hand.extend(cards)


class 称象(Skill):
    """
    当你受到伤害后，你可以亮出牌堆顶的四张牌，然后你获得其中的任意张点数之和不大于13的牌。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        return player is self.owner and event.who is player and event.what == "受到伤害后"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            cards = [game.draw_from_deck() for _ in range(4)]
            print(f"{player}发动了技能{self}，亮出了牌堆顶的4张牌：{'、'.join(str(c) for c in cards)}")
            max_rank = 13
            cards_chosen = []
            while cards:
                options = [card for card in cards if card.rank_value() <= max_rank]
                if not options:
                    break
                card = options[player.agent().choose(options, use_skill_event, f"请选择一张由{self}得到的牌")]
                cards.remove(card)
                cards_chosen.append(card)
                max_rank -= card.rank_value()
            if cards_chosen:
                print(f"{player}获得了{'、'.join(str(c) for c in cards_chosen)}")
                player.hand.extend(cards_chosen)
            if cards:
                print(f"{'、'.join(str(c) for c in cards)}进入了弃牌堆")
                game.discard(cards)


class 仁心v1(Skill):
    """
    当一名其他角色处于濒死状态时，你可以交给其一张♥牌。若如此做，该角色恢复1点体力，然后你受到1点无来源的伤害。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is not player and event.what == "dying" and \
               player.cards(suits="♥") and event.who.hp <= 0

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            options = player.cards(suits="♥", return_places=True)
            place, card = options[player.agent().choose(options, use_skill_event)]
            target = event.who
            print(f"{player}发动了技能{self}，将{place}{card}交给了{target}")
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            game.lose_card(player, card, place[0], "交给", cost_event)
            target.hand.append(card)
            game.recover(target, 1, use_skill_event)
            game.damage(player, 1, None, cost_event)


class 仁心v2(Skill):
    """
    当其他角色受到伤害时，若伤害值不小于该角色体力值，你可以翻面并弃置一张装备牌，然后防止此伤害。
    """

    def can_use(self, player, event):  # 受到伤害时 <- damage
        return player is self.owner and event.who is not player and event.what == "受到伤害时" \
               and event.cause.n >= event.who.hp and player.cards(types=C_("装备牌"))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(types=C_("装备牌"), return_places=True)
        place, card = options[player.agent().choose(options, cost_event, "请选择要弃置的装备牌")]
        damage = event.cause
        print(f"{player}发动了技能{self}，弃置了{place}{card}，防止了{damage.who}对{damage.whom}造成的{damage.n}点伤害")
        game.lose_card(player, card, place[0], "弃置", cost_event)
        game.table.append(card)
        game.flip(player, cost_event)
        return 0


仁心 = 仁心v2


class 精策(Skill):
    """
    结束阶段，若你于此回合内使用过的牌数量不小于你的体力值，则你可以摸两张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.counter = 0

    def can_use(self, player, event):
        if player is not self.owner or event.who is not player:
            return False
        return event.what in ["turn_start", "use_card", "respond"] \
               or event.what == "turn_end" and self.counter >= player.hp

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.counter = 0
        elif event.what in ["use_card", "respond"]:
            self.counter += 1
        else:
            game = player.game
            use_skill_event = UseSkillEvent(player, self, cause=event)
            if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}")
                game.deal_cards(player, 2)
        return data


class 峻刑(Skill):
    """
    出牌阶段限一次，你可以弃置任意张手牌并选择一名其他角色，然后令其选择一项：
    1. 弃置与你弃置的牌类别均不同的一张手牌；2. 翻面，然后将手牌摸至四张。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and player.hand

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        options = [p for p in game.iterate_live_players() if p is not player]
        target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
        use_skill_event.targets = [target]
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards("手")
        cards = [options[i] for i in
                 player.agent().choose_many(options, (1, len(options)), cost_event, "请选择要弃置的手牌")]
        print(f"{player}对{target}发动了技能{self}，弃置了手牌{'、'.join(str(c) for c in cards)}")
        for card in cards:
            game.lose_card(player, card, "手", "弃置", cost_event)
        game.table.extend(cards)
        options = ["翻面，然后将手牌摸至四张"]
        classes = {card.type.class_ for card in cards}
        discard_options = [card for card in target.hand if card.type.class_ not in classes]
        if discard_options:
            options.append(f"弃置与{player}弃置的牌类别均不同的一张手牌")
        if target.agent().choose(options, use_skill_event, "请选择"):
            card = discard_options[target.agent().choose(discard_options, use_skill_event, "请选择要弃置的手牌")]
            print(f"{target}弃置了手牌{card}")
            game.lose_card(target, card, "手", "弃置", use_skill_event)
            game.table.append(card)
        else:
            game.flip(target, use_skill_event)
            n = 4 - len(target.hand)
            game.deal_cards(target, n)
        self.use_quota -= 1


class 御策(Skill):
    """
    当你受到伤害后，你可以展示一张手牌，然后除非伤害来源弃置与你展示的牌类别不同的一张手牌，否则你回复1点体力。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        return player is self.owner and event.who is player and event.what == "受到伤害后" and player.hand

    def use(self, player, event, data=None):
        game = player.game
        inflicter = event.cause.who
        use_skill_event = UseSkillEvent(player, self, [inflicter], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            options = player.hand
            card_shown = options[player.agent().choose(options, use_skill_event, "请选择要展示的手牌")]
            print(f"{player}发动了技能{self}，展示了手牌{card_shown}")
            if inflicter:
                options = [f"令{player}回复1点体力"]
                discard_options = [card for card in inflicter.hand if card.type.class_ != card_shown.type.class_]
                if discard_options:
                    options.append(f"弃置与{card_shown}类别不同的一张手牌")
                if inflicter.agent().choose(options, use_skill_event, "请选择"):
                    card = discard_options[inflicter.agent().choose(discard_options, use_skill_event, "请选择要弃置的手牌")]
                    print(f"{inflicter}弃置了手牌{card}")
                    game.lose_card(inflicter, card, "手", "弃置", use_skill_event)
                    game.table.append(card)
                else:
                    game.recover(player, 1, use_skill_event)


class 司敌(Skill):
    """
    其他角色出牌阶段开始时，你可以弃置一张非基本牌，然后该角色不能使用和打出与此牌颜色相同的牌。
    此阶段结束时，若其没有使用【杀】，视为你对其使用一张【杀】。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.ban_color = None
        self.attacked = False

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "phase_start":
            return event.who is not player and event.args["phase"] == "出牌阶段" and \
                   player.cards(types=(C_("锦囊牌"), C_("装备牌")))
        elif event.what == "test_use_prohibited":
            return self.ban_color and core.color(event.args["cards"]) == self.ban_color
        elif event.what == "use_card":
            return self.ban_color and issubclass(event.card_type, C_("杀"))
        elif event.what == "phase_end":
            return self.ban_color
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "phase_start":
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                options = player.cards(types=(C_("锦囊牌"), C_("装备牌")), return_places=True)
                place, card = options[player.agent().choose(options, use_skill_event, "请选择要弃置的牌")]
                print(f"{player}发动了技能{self}，弃置了{place}{card}")
                cost_event = Event(player, "use_skill_cost", use_skill_event)
                game.lose_card(player, card, place[0], "弃置", cost_event)
                game.table.append(card)
                self.ban_color = core.color([card])
            return
        elif event.what == "test_use_prohibited":
            return True
        elif event.what == "use_card":
            self.attacked = True
            return
        else:  # event.what == "phase_end"
            if not self.attacked:
                target = event.who
                print(f"{player}的技能{self}被触发，视为{player}对{target}使用了一张杀")
                C_("杀").effect(player, [], [target])
            self.ban_color = None
            self.attacked = False


class 品第(Skill):
    """
    出牌阶段，你可以弃置一张牌并选择一名角色（每回合每种类型的牌限一次且每名角色限一次），
    你令其摸X张牌或弃置X张牌（X为本回合此技能发动次数），然后你翻面。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_count = 0
        self.card_classes = set()
        self.targets = set()

    def legal_targets(self):
        return [p for p in self.owner.game.iterate_live_players() if p not in self.targets]

    def card_options(self, player):
        return [(place, card) for place, card in
                player.cards(return_places=True) if card.type.class_ not in self.card_classes]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "play":
            return self.card_options(player) and self.legal_targets()
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_count = 0
            self.card_classes = set()
            self.targets = set()
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = self.card_options(player)
        place, card = options[player.agent().choose(options, cost_event, "请选择要弃置的牌")]
        options = self.legal_targets()
        target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
        print(f"{player}对{target}发动了技能{self}，弃置了{place}{card}")
        game.lose_card(player, card, place[0], "弃置", cost_event)
        game.table.append(card)
        self.use_count += 1
        self.card_classes.add(card.type.class_)
        self.targets.add(target)
        n = self.use_count
        if player.agent().choose([f"令{target}摸{n}张牌", f"令{target}弃置{n}张牌"], cost_event, "请选择"):
            target.discard_n_cards(n, use_skill_event)
        else:
            game.deal_cards(target, n)
        game.flip(player, use_skill_event)


class 法恩(Skill):
    """
    当一名角色的武将牌翻至背面或横置后，你可以令其摸一张牌。
    """

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "flip":
            return event.who.flipped
        elif event.what == "chain":
            return event.who.chained
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        target = event.who
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            game.deal_cards(target, 1)


class 慎断(Skill):
    """
    当你的一张黑色基本牌因弃置而放入弃牌堆后，你可以将此牌当无距离限制的【兵粮寸断】使用。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = False

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "弃牌阶段":
            return True
        elif event.what == "modify_use_range":
            return self.buff and issubclass(event.args["card_type"], C_("兵粮寸断"))
        else:
            return False
        # TODO: Discard in cases other than 弃牌阶段

    def use(self, player, event, data=None):
        if event.what == "modify_use_range":
            return None
        # event.what == "弃牌阶段"
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        ctype = C_("兵粮寸断")
        self.buff = True
        cards = [card for card in data if card.suit in "♠♣" and card.type.class_ == "基本牌"]
        while cards and player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            card = cards[player.agent().choose(cards, use_skill_event, "请选择一张黑色基本牌")]
            try:
                args = ctype.get_args(player, [card])
            except core.NoOptions:
                print(f"{player}想要发动技能{self}，但中途取消")
                break
            print(f"{player}发动了技能{self}，将{card}当{ctype.__name__}对{args[0]}使用")
            data.remove(card)
            cards.remove(card)
            game.table.append(card)
            ctype.effect(player, [card], args)
        self.buff = False
        return data


class 勇略(Skill):
    """
    其他角色的判定阶段开始时，若其在你攻击范围内，你可以弃置其判定区里的一张牌，然后视为你对其使用一张【杀】，
    若此【杀】没有造成过伤害，则你摸一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = False

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        game = player.game
        if event.what == "phase_start":
            target = event.who
            return event.args["phase"] == "判定阶段" and target.判定区 and game.can_attack(player, target)
        elif event.what == "造成伤害后":
            return event.who is player and self.buff
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "造成伤害后":
            self.buff = False
            return
        # event.what == "phase_start"
        game = player.game
        target = event.who
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        _, card = game.pick_card(player, target, "判", use_skill_event, "请选择要弃置的牌")
        print(f"{player}发动了技能{self}，弃置了{target}判定区的牌{card}，视为对{target}使用了一张杀")
        game.lose_card(target, card, "判", "弃置", use_skill_event)
        game.table.append(card)
        self.buff = True
        C_("杀").effect(player, [], [target])
        if self.buff:
            game.deal_cards(player, 1)
        self.buff = False


class 笔伐(Skill):
    """
    其他角色的回合开始时，你可以打出一张手牌，然后令该角色选择一项：1. 交给你一张类别相同的手牌，并获得此牌；2. 失去1点体力。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is not player and event.what == "turn_start" and player.hand

    def use(self, player, event, data=None):
        game = player.game
        target = event.who
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            card = player.hand[player.agent().choose(player.hand, use_skill_event, "请选择要打出的手牌")]
            print(f"{player}对{target}发动了技能{self}，打出了手牌{card}")
            game.lose_card(player, card, "手", "打出", use_skill_event)
            options = ["失去1点体力"]
            card_options = target.cards("手", types=C_(card.type.class_))
            if card_options:
                options.append(f"交给{player}一张与{card}类别相同的手牌，并获得{card}")
            if target.agent().choose(options, use_skill_event, "请选择"):
                card_to_give = card_options[target.agent().choose(card_options, use_skill_event,
                                                                  f"请选择要交给{player}的手牌")]
                print(f"{target}将手牌{card_to_give}交给了{player}，并获得了{card}")
                game.lose_card(target, card_to_give, "手", "获得", use_skill_event)
                player.hand.append(card_to_give)
                target.hand.append(card)
            else:
                print(f"{target}失去了1点体力")
                game.lose_health(target, 1, use_skill_event)
                game.table.append(card)


class 颂词(Skill):
    """
    出牌阶段，你可以选择一项：1. 令一名手牌数小于其体力值的角色摸两张牌；2. 令一名手牌数大于其体力值的角色弃置两张牌。每名角色限一次。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.targets_used = set()

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p not in self.targets_used and len(p.hand) != p.hp]

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "play" and self.legal_targets(player)

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
        print(f"{player}对{target}发动了技能{self}")
        use_skill_event.targets = [target]
        self.targets_used.add(target)
        if len(target.hand) < target.hp:
            game.deal_cards(target, 2)
        else:
            target.discard_n_cards(2, use_skill_event)


class 设伏(Skill):
    """
    结束阶段，你可以将一张基本牌或锦囊牌扣置于你的武将牌上，称为“伏兵”。当其他角色使用牌时，你可以移去一张名称相同的“伏兵”，令此牌无效。
    """

    def ambush(self, card_type):
        cards = [card for card in self.owner.repo if issubclass(card_type, card.type)]
        return cards

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "turn_end":
            return event.who is player and player.cards("手", types=(C_("基本牌"), C_("锦囊牌")))
        elif event.what == "test_card_nullify":  # test_card_nullify(target) <- use_card(user, card_type)
            event0 = event.cause
            return event0.who is not player and self.ambush(event0.card_type)
            # TODO: nullify for all players instead of just one player
            # TODO: nullify responded cards also (杀, 闪, 桃, 酒, 无懈可击)

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        if event.what == "turn_end":
            options = player.cards("手", types=(C_("基本牌"), C_("锦囊牌")))
            card = options[player.agent().choose(options, cost_event, "请选择作为“伏兵”的牌")]
            print(f"{player}发动了技能{self}，将一张手牌扣置于武将牌上作为“伏兵”")
            game.lose_card(player, card, "手", "置入", cost_event)
            player.repo.append(card)
            player.show_repo = False
        else:  # event.what == "test_card_nullify"
            ctype = event.cause.card_type
            options = self.ambush(ctype)
            card = options[player.agent().choose(options, cost_event, "请选择要移去的“伏兵”牌")]
            print(f"{player}发动了技能{self}，移去了“伏兵”牌{card}，令{ctype.__name__}无效")
            player.repo.remove(card)
            game.discard([card])
            return True


class 贲育(Skill):
    """
    当你受到伤害后，你可以选择一项：1. 将手牌摸至与伤害来源手牌数相同（最多摸至5张）；2. 弃置大于伤害来源手牌数的手牌，然后对其造成1点伤害。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        if not (player is self.owner and event.who is player and event.what == "受到伤害后"):
            return False
        inflicter = event.cause.who
        return inflicter is not None and len(inflicter.hand) != len(player.hand)

    def use(self, player, event, data=None):
        game = player.game
        inflicter = event.cause.who
        use_skill_event = UseSkillEvent(player, self, [inflicter], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            n = len(player.hand) - len(inflicter.hand)
            if n > 0:
                cost_event = Event(player, "use_skill_cost", use_skill_event)
                options = player.hand
                cards = [options[i] for i in
                         player.agent().choose_many(options, n, event=cost_event, message="请选择要弃置的手牌")]
                print(f"{player}发动了技能{self}，弃置了手牌{'、'.join(str(c) for c in cards)}")
                for card in cards:
                    game.lose_card(player, card, "手", "弃置", cost_event)
                game.discard(cards)
                game.damage(inflicter, 1, player, use_skill_event)
            else:
                n_draw = min(-n, 5 - len(player.hand))
                print(f"{player}发动了技能{self}")
                game.deal_cards(player, n_draw)


class 功獒(Skill):
    """
    锁定技，每其他角色死亡后，你加1点体力上限，然后回复1点体力。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is not player and event.what == "die"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        print(f"{player}的技能{self}被触发")
        game.change_hp_cap(player, 1, use_skill_event)
        game.recover(player, 1, use_skill_event)


class 举义(Skill):
    """
    觉醒技，准备阶段，若你已受伤且体力上限大于全场角色数，你将手牌摸至等同于体力上限的张数，然后获得“崩坏”和“威重”。
    """
    labels = {"觉醒技"}

    def can_use(self, player, event):
        game = player.game
        return (player is self.owner and event.who is player and event.what == "before_turn_start"
                and player.is_wounded() and player.hp_cap > len(game.alive))

    def use(self, player, event, data=None):
        game = player.game
        print(f"{player}的技能{self}被触发")
        n = player.hp_cap - len(player.hand)
        game.deal_cards(player, n)
        print(f"{player}获得了技能“崩坏”和“威重”")
        player.skills = player.skills[:]  # Avoid modifying the list when iterating through it in Game.trigger_skills()
        player.skills.remove(self)
        player.skills.append(崩坏(player))
        player.skills.append(威重(player))
        game.trigger_skills(Event(player, "wake"))


class 威重(Skill):
    """
    锁定技，当你的体力上限变化时，你摸一张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "change_hp_cap"

    def use(self, player, event, data=None):
        game = player.game
        print(f"{player}的技能{self}被触发")
        game.deal_cards(player, 1)


# ======= 吴 =======
class 短兵(Skill):
    """
    你使用【杀】可以额外选择一名距离为1的角色为目标。
    """

    def can_use(self, player, event):  # confirm_targets <- use_card
        if not (player is self.owner and event.who is player and event.what == "confirm_targets"):
            return False
        event0 = event.cause
        return event0.what == "use_card" and issubclass(event0.card_type, C_("杀"))

    def use(self, player, event, data=None):
        game = player.game
        options = [p for p in game.iterate_live_players() if game.distance(player, p) == 1 and p not in data]
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not options or not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        target = options[player.agent().choose(options, use_skill_event, f"请选择额外的目标")]
        print(f"{player}发动了技能{self}，选择了{target}作为杀的额外目标")
        return data + [target]


class 奋迅(Skill):
    """
    出牌阶段限一次，你可以弃置一张牌并选择一名其他角色，然后你与该角色的距离视为1，直到回合结束。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1
        self.victim = None

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "play":
            return self.use_quota > 0 and player.total_cards() > 0
        elif event.what == "calc_distance":
            return event.args["to"] is self.victim
        elif event.what == "turn_end":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        elif event.what == "calc_distance":
            return 1
        elif event.what == "turn_end":
            self.victim = None
            return
        # event.what == "play"
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = [p for p in game.iterate_live_players() if p is not player]
        target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
        print(f"{player}对{target}发动了技能{self}")
        player.discard_n_cards(1, cost_event)
        self.victim = target
        self.use_quota -= 1


class 疑城(Skill):
    """
    当一名与你势力相同的角色成为【杀】的目标后，你可以令该角色摸一张牌，然后其弃置一张牌。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.what == "use_card" and issubclass(event.card_type, C_("杀"))):
            return False
        for p in event.targets:
            if p.faction == player.faction:
                return True
        return False

    def use(self, player, event, data=None):
        game = player.game
        targets = [p for p in event.targets if p.faction == player.faction]
        for target in targets:
            use_skill_event = UseSkillEvent(player, self, [target], event)
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否对{target}发动技能{self}"):
                print(f"{player}对{target}发动了技能{self}")
                game.deal_cards(target, 1)
                target.discard_n_cards(1, use_skill_event)


# class 旋风(Skill):
    """
    当你于弃牌阶段弃置过至少两张牌，或当你失去装备区里的牌后，你可以弃置至多两名其他角色的共计两张牌。
    """


class 旋略(Skill):
    """
    当你失去装备区里的牌后，你可以弃置一名其他角色的一张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "lose_card" and event.zone == "装"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            options = [p for p in game.iterate_live_players() if p is not player and p.total_cards() > 0]
            target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
            print(f"{player}对{target}发动了技能{self}")
            place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择要弃置的{target}的牌")
            print(f"{player}弃置了{target}的{place}{card}")
            game.lose_card(target, card, place[0], "弃置", use_skill_event)
            game.table.append(card)


class 勇进(Skill):
    """
    限定技，出牌阶段，你可以移动场上的至多三张装备牌。
    """

    labels = {"限定技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "play" and not self.used

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        print(f"{player}发动了技能{self}")
        for i_move in range(3):
            options = [p for p in game.iterate_live_players() if p.装备区]
            if not options:
                break
            if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}移动第{i_move}张牌"):
                break
            target = options[player.agent().choose(options, use_skill_event, f"请选择要移走第{i_move}张装备区的牌的角色")]
            _, card = game.pick_card(player, target, "装", use_skill_event, f"请选择要移走的{target}的装备区的牌")
            key = None
            for k, val in target.装备区.items():
                if val is card:
                    key = k
                    break
            options = [p for p in game.iterate_live_players() if p is not target and key not in p.装备区]
            if not options:
                continue
            second_arg = options[player.agent().choose(options, use_skill_event,
                                                       f"请选择要将{target}的装备区的牌{card}转移给哪名角色")]
            print(f"{player}将{target}的装备区的牌{card}转移给了{second_arg}")
            game.lose_card(target, card, "装", "置入", use_skill_event)
            second_arg.装备区[key] = card
        self.used = True


class 补益(Skill):
    """
    一名角色进入濒死状态时，你可以展示其一张手牌，然后若此牌不为基本牌，则其弃置此牌，然后回复1点体力。
    """

    def can_use(self, player, event):
        return player is self.owner and event.what == "dying" and event.who.hand and event.who.hp <= 0

    def use(self, player, event, data=None):
        game = player.game
        target = event.who
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            if target is not player:
                card = random.choice(target.hand)
            else:
                options = target.hand
                card = options[player.agent().choose(options, use_skill_event, "请选择要弃置的手牌")]
            print(f"{player}发动了技能{self}，展示了{target}的手牌{card}")
            if not issubclass(card.type, C_("基本牌")):
                print(f"{target}弃置了手牌{card}")
                game.lose_card(target, card, "手", "弃置", use_skill_event)
                game.table.append(card)
                game.recover(target, 1, use_skill_event)


class 甘露(Skill):
    """
    出牌阶段限一次，你可以选择两名装备区里的牌数之差不大于你已损失体力值的角色，交换他们装备区里的牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self)
        options = [p for p in game.iterate_live_players()]
        target1 = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的第一个目标")]
        use_skill_event.targets = [target1]
        n1, diff = len(target1.装备区), player.hp_cap - player.hp
        options = [p for p in options if p is not target1 and n1 - diff <= len(p.装备区) <= n1 + diff]
        if not options:
            print(f"{player}想要发动技能{self}，但中途取消")
            return
        target2 = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的第二个目标")]
        print(f"{player}发动了技能{self}，令{target1}和{target2}交换装备区的牌")
        use_skill_event.targets.append(target2)
        cards1, cards2 = target1.cards("装"), target2.cards("装")
        equips1, equips2 = dict(target1.装备区), dict(target2.装备区)
        if cards1:
            print(f"{target1}装备区的牌{'、'.join(str(c) for c in cards1)}转移到了{target2}的装备区")
        if cards2:
            print(f"{target2}装备区的牌{'、'.join(str(c) for c in cards2)}转移到了{target1}的装备区")
        for card in cards1:
            game.lose_card(target1, card, "装", "获得", use_skill_event)
        for card in cards2:
            game.lose_card(target2, card, "装", "获得", use_skill_event)
        target1.装备区 = equips2
        target2.装备区 = equips1
        self.use_quota -= 1


class 缓释(Skill):
    """
    一名角色的判定牌生效前，你可以令其观看你的手牌并选择你的一张牌，然后你打出此牌代替判定牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.what == "judge" and player.total_cards() > 0

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        judgment = data
        target = event.who
        options = player.cards(return_places=True)
        print(f"{player}发动了技能{self}，令{target}观看其手牌并选择一张牌")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        place, card = options[target.agent().choose(options, cost_event, f"请选择{player}的一张牌作为判定牌")]
        print(f"{player}发动了技能{self}，打出了{place}{card}代替判定牌")
        game.lose_card(player, card, place[0], "打出", cost_event)
        game.table.append(judgment)  # Game.judge will add judge result to the table
        return card


class 弘援(Skill):
    """
    摸牌阶段，你可以少摸一张牌，然后令至多两名其他角色各摸一张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "摸牌阶段"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        options = [p for p in game.iterate_live_players() if p is not player]
        targets = [options[i] for i in player.agent().choose_many(options, (1, 2), use_skill_event, "请选择目标角色")]
        print(f"{player}发动了技能{self}，令{'、'.join(str(p) for p in targets)}摸牌")
        for p in targets:
            game.deal_cards(p, 1)
        return data - 1


class 明哲(Skill):
    """
    你的回合外，当你使用、打出或弃置一张红色牌时，你可以摸一张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and player.game.current_player() is not player and event.who is player and \
               event.what == "lose_card" and event.type in ["使用", "打出", "弃置"] and event.card.suit in "♥♦"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            player.game.deal_cards(player, 1)


class 安恤(Skill):
    """
    出牌阶段限一次，你可以选择两名手牌数不同的其他角色，令其中手牌多的角色将一张手牌交给手牌少的角色。
    然后若这两名角色手牌数相等，你摸一张牌或回复1点体力。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def legal_targets(self, player):
        game = player.game
        for p in game.iterate_live_players():
            if p is player:
                continue
            if next(self.legal_second_args(player, p), None) is not None:
                yield p

    def legal_second_args(self, player, first_arg):
        game = player.game
        for p in game.iterate_live_players():
            if p is not player and len(p.hand) < len(first_arg.hand):
                yield p

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "turn_start" or
                event.what == "play" and self.use_quota > 0 and next(self.legal_targets(player), None) is not None)

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        options = list(self.legal_targets(player))
        target = options[player.agent().choose(options, use_skill_event, "请选择手牌数多的目标角色")]
        use_skill_event.targets = [target]
        options = list(self.legal_second_args(player, target))
        second_arg = options[player.agent().choose(options, use_skill_event, "请选择手牌数少的目标角色")]
        use_skill_event.targets.append(second_arg)
        print(f"{player}发动了技能{self}，令{target}将一张手牌交给{second_arg}")
        card = target.hand[target.agent().choose(target.hand, use_skill_event, f"请选择要交给{second_arg}的手牌")]
        print(f"{target}将一张手牌交给了{second_arg}")
        game.lose_card(target, card, "手", "获得", use_skill_event)
        second_arg.hand.append(card)
        if len(target.hand) == len(second_arg.hand):
            options = ["摸一张牌"]
            if player.is_wounded():
                options.append("回复1点体力")
            if player.agent().choose(options, use_skill_event, "请选择"):
                game.recover(player, 1, use_skill_event)
            else:
                game.deal_cards(player, 1)
        self.use_quota -= 1


class 追忆(Skill):
    """
    当你死亡时，你可以令一名其他角色（杀死你的角色除外）摸三张牌。若如此做，该角色回复1点体力。
    """

    def can_use(self, player, event):  # die <- damage
        return player is self.owner and event.who is player and event.what == "die"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        killer = None
        if event.cause.what == "damage":
            killer = event.cause.who
        options = [p for p in game.iterate_live_players() if p is not player and p is not killer]
        if options and player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
            use_skill_event.targets = [target]
            print(f"{player}对{target}发动了技能{self}")
            game.deal_cards(target, 3)
            game.recover(target, 1, use_skill_event)


class 疠火(Skill):
    """
    你使用的普通【杀】可以改为火【杀】，若此【杀】造成过伤害，你失去1点体力；你使用火【杀】可以多选择一个目标。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.cool = True
        self.n_damage = 0

    def can_use(self, player, event):
        ctype = C_("火杀")
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "play":
            cards = [card for card in player.hand if card.type == C_("杀")]
            return cards and ctype.can_use(player, [])
        elif event.what == "modify_n_targets":
            return issubclass(event.args["card_type"], ctype)
        elif event.what == "造成伤害后":  # 造成伤害后 <- damage <- use_card
            event0 = event.cause.cause
            return not self.cool and event0.what == "use_card" and issubclass(event0.card_type, ctype)
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        if event.what == "modify_n_targets":
            return data + 1
        elif event.what == "造成伤害后":
            # print(f"{player}的技能{self}被触发，{player}失去1点体力")
            # game.lose_health(player, 1, cost_event)
            self.n_damage += event.cause.n
            return
        # event.what == "play"
        ctype = C_("火杀")
        options = [card for card in player.hand if card.type == C_("杀")]
        card = options[player.agent().choose(options, cost_event, "请选择一张普通杀")]
        args = ctype.get_args(player, [card])
        print(f"{player}发动了技能{self}，将{card}当火杀对{'、'.join(str(target) for target in args)}使用")
        game.lose_card(player, card, "手", "使用", cost_event)
        game.table.append(card)
        self.cool = False
        self.n_damage = 0
        ctype.effect(player, [card], args)
        if self.n_damage > 0:
            print(f"{player}的技能{self}被触发，{player}失去1点体力")
            game.lose_health(player, 1, cost_event)
        self.cool = True


class 醇醪(Skill):
    """
    结束阶段，若你没有“醇”，你可以将任意张【杀】置于武将牌上，称为“醇”；当一名角色处于濒死状态时，你可以移去一张“醇”，视为该角色使用一张【酒】。
    """

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "turn_end":
            return event.who is player and not player.repo and player.cards(types=C_("杀"))
        # elif event.what == "card_asked":  # card_asked <- dying
        #     return player.repo and issubclass(event.args["card_type"], C_("酒")) and event.cause.what == "dying"
        # TODO: This doesn't work now because response to card_asked should be initiated by the player asked
        elif event.what == "dying":
            return player.repo and event.who.hp <= 0
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "turn_end":
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                options = player.cards("手", types=C_("杀"))
                cards = [options[i] for i in player.agent().choose_many(options, (1, len(options)), use_skill_event,
                                                                                  "请选择任意数量的杀置于武将牌上作为“醇”")]
                print(f"{player}发动了技能{self}，将{'、'.join(str(c) for c in cards)}置于武将牌上作为“醇”")
                cost_event = Event(player, "use_skill_cost", use_skill_event)
                for card in cards:
                    game.lose_card(player, card, "手", "置于", cost_event)
                player.repo.extend(cards)
            return
        # # card_asked
        # provided, cards = data
        # target = event.who
        # use_skill_event.targets = [target]
        # if provided or not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
        #     return data
        # options = player.repo
        # card = options[player.agent().choose(options, use_skill_event, "请选择要弃置的“醇”")]
        # print(f"{player}发动了技能{self}，弃置了一张“醇”（{card}），视为{target}使用了一张酒")
        # player.repo.remove(card)
        # game.table.append(card)
        # return provided, [card]

        # dying
        target = event.who
        use_skill_event.targets = [target]
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        options = player.repo
        n_needed = 1 - target.hp
        n_max = min(n_needed, len(options))
        cards = [options[i] for i in
                 player.agent().choose_many(options, (1, n_max), use_skill_event, "请选择要弃置的“醇”")]
        n = len(cards)
        print(f"{player}发动了技能{self}，弃置了{n}张“醇”（{'、'.join(str(c) for c in cards)}），视为{target}使用了{n}张酒")
        for card in cards:
            player.repo.remove(card)
        game.table.extend(cards)
        game.recover(target, n, use_skill_event)


class 弓骑(Skill):
    """
    出牌阶段限一次，你可以弃置一张牌使你本回合的攻击范围无限。若弃置的为装备牌，你可以弃置一名其他角色的一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = False

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        elif event.what == "play":
            return not self.buff and player.total_cards() > 0
        elif event.what == "modify_use_range":
            return self.buff and issubclass(event.args["card_type"], C_("杀"))
        elif event.what == "turn_end":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "modify_use_range":
            return None
        elif event.what == "turn_end":
            self.buff = False
            return
        # event.what == "play"
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(return_places=True)
        place, card = options[player.agent().choose(options, cost_event, "请选择要弃置的牌")]
        print(f"{player}发动了技能{self}，弃置了{place}{card}")
        game.lose_card(player, card, place[0], "弃置", cost_event)
        game.table.append(card)
        self.buff = True
        if issubclass(card.type, C_("装备牌")):
            options = [p for p in game.iterate_live_players() if p is not player and p.total_cards() > 0]
            if options and player.agent().choose(["不发动", "发动"], use_skill_event, "请选择是否弃置其他角色的一张牌"):
                target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
                place, card = game.pick_card(player, target, "手装", use_skill_event, "请选择要弃置的牌")
                print(f"{player}弃置了{target}{place}{card}")
                game.lose_card(target, card, place[0], "弃置", use_skill_event)
                game.table.append(card)


class 解烦(Skill):
    """
    限定技，出牌阶段，你可以选择一名角色，令能攻击到该角色的所有角色选择一项：弃置一张武器牌；或令该角色摸一张牌。
    """

    labels = {"限定技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "play" and not self.used

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        options = [p for p in game.iterate_live_players()]
        target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
        print(f"{player}对{target}发动了技能{self}")
        for p in game.iterate_live_players():
            if game.can_attack(p, target):
                options = [f"令{target}摸一张牌"]
                weapons = p.cards(types=C_("武器"), return_places=True)
                if weapons:
                    options.append("弃置一张武器牌")
                if p.agent().choose(options, use_skill_event, f"请选择如何响应{player}的技能{self}"):
                    place, card = weapons[p.agent().choose(weapons, use_skill_event, "请选择要弃置的武器牌")]
                    print(f"{p}弃置了{place}{card}")
                    game.lose_card(p, card, place[0], "弃置", use_skill_event)
                    game.table.append(card)
                else:
                    print(f"{p}令{target}摸牌")
                    game.deal_cards(target, 1)
        self.used = True


class 夺刀(Skill):
    """
    当你受到【杀】造成的伤害后，你可以弃置一张牌，然后获得伤害来源装备区里的武器牌。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage <- use_card
        if not (player is self.owner and event.who is player and event.what == "受到伤害后"):
            return False
        event0 = event.cause.cause
        return event0.who is not player and event0.what == "use_card" and issubclass(event0.card_type, C_("杀")) \
               and "武器" in event0.who.装备区

    def use(self, player, event, data=None):
        game = player.game
        target = event.cause.who
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        print(f"{player}发动了技能{self}")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        player.discard_n_cards(1, cost_event)
        weapon = target.装备区["武器"]
        print(f"{player}获得了{target}的武器牌{weapon}")
        game.lose_card(target, weapon, "装", "获得", use_skill_event)
        player.hand.append(weapon)


class 暗箭(Skill):
    """
    锁定技，当你使用【杀】对目标角色造成伤害时，若你不在其攻击范围内，则此伤害+1。
    """

    def can_use(self, player, event):  # 造成伤害时 <- damage <- use_card
        if not (player is self.owner and event.who is player and event.what == "造成伤害时"):
            return False
        event0 = event.cause.cause
        victim = event.cause.whom
        return event0.who is player and event0.what == "use_card" and issubclass(event0.card_type, C_("杀")) \
               and not player.game.can_attack(victim, player)

    def use(self, player, event, data=None):
        print(f"{player}的技能{self}被触发，伤害+1")
        return data + 1


class 纵玄(Skill):
    """
    当你的牌因弃置而放入弃牌堆后，你可以将其中任意张牌置于牌堆顶。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "弃牌阶段"
        # TODO: discard in other occasions

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not data or not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        print(f"{player}发动了技能{self}")
        cards = [data[i] for i in
                 player.agent().choose_many(data, (1, len(data)), use_skill_event, "请选择并排列放置于牌堆顶的牌")]
        print(f"{player}将{len(cards)}张牌置于牌堆顶")
        for card in cards:
            data.remove(card)
        game.deck.extend(cards[::-1])
        return data


class 直言(Skill):
    """
    结束阶段，你可以令一名角色摸一张牌并展示之，若此牌为装备牌，则该角色使用此牌，然后其回复1点体力。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_end"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        options = [p for p in game.iterate_live_players()]
        target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
        card = game.draw_from_deck()
        print(f"{player}发动了技能{self}，令{target}摸了一张牌{card}")
        target.hand.append(card)
        if issubclass(card.type, C_("装备牌")):
            game.use_card(target, card)
            game.recover(target, 1, use_skill_event)


class 胆守(Skill):
    """
    每名角色的回合限一次，当你成为基本牌或锦囊牌的目标后，你可以摸X张牌（X为你本回合成为基本牌或锦囊牌的目标次数）；
    当前回合角色的结束阶段，若你本回合没有以此法摸牌，你可以弃置与其手牌数相同的牌数（无牌则不弃） 对其造成1点伤害。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False
        self.cnt = 0

    def can_use(self, player, event):
        if player is not self.owner or event.who is player:
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "use_card":
            return not self.used and player in event.targets
        elif event.what == "turn_end":
            return not self.used and event.who.is_alive() and player.total_cards() >= len(event.who.hand)
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "turn_start":
            self.used = False
            self.cnt = 0
            return
        elif event.what == "use_card":
            self.cnt += 1
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}摸{self.cnt}张牌"):
                print(f"{player}发动了技能{self}")
                game.deal_cards(player, self.cnt)
                self.used = True
            return
        # event.what == "turn_end"
        target = event.who
        use_skill_event.targets = [target]
        if player.agent().choose(["不发动", "发动"], use_skill_event,
                                 f"请选择是否发动技能{self}，弃置{len(target.hand)}张牌对{target}造成1点伤害"):
            print(f"{player}发动了技能{self}")
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            player.discard_n_cards(len(target.hand), cost_event)
            game.damage(target, 1, player, use_skill_event)



class 慎行(Skill):
    """
    出牌阶段，你可以弃置两张牌，然后摸一张牌。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "play" and player.total_cards() >= 2

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, None, event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        print(f"{player}发动了技能{self}")
        player.discard_n_cards(2, cost_event)
        game.deal_cards(player, 1)


class 秉壹(Skill):
    """
    结束阶段，你可以展示所有手牌，若颜色均相同，你令至多X名角色各摸一张牌（X为你的手牌数）。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_end" and player.hand

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}，展示了手牌{'、'.join(str(c) for c in player.hand)}")
            if core.color(player.hand) != "no_color":
                n = len(player.hand)
                options = [p for p in game.iterate_live_players()]
                targets = [options[i] for i in
                           player.agent().choose_many(options, (1, n), use_skill_event, "请选择目标角色")]
                for p in targets:
                    game.deal_cards(p, 1)


class 谮毁(Skill):
    """
    出牌阶段限一次，当你使用【杀】或黑色普通锦囊牌仅指定唯一目标时，你可以令能成为此牌目标的另一名角色选择一项：
    1. 交给你一张牌，然后代替你成为此牌的使用者；
    2. 也成为此牌的目标。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 0

    def can_use(self, player, event):  # confirm_targets <- use_card
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "confirm_targets":
            event0 = event.cause
            ctype = event0.card_type
            return self.use_quota > 0 and len(event0.targets) == 1 and \
                   (issubclass(ctype, C_("杀")) or
                    issubclass(ctype, C_("即时锦囊")) and core.color(event0.cards) == "black")
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        event0 = event.cause
        ctype, cards, target0 = event0.card_type, event0.cards, event0.targets[0]
        options = [p for p in game.iterate_live_players() if
                   p not in (player, target0) and ctype.target_legal(player, p, cards)]
        if not options or not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标角色")]
        print(f"{player}对{target}发动了技能{self}")
        self.use_quota -= 1
        options = [f"成为{player}对{target0}使用的{ctype.__name__}的额外目标"]
        card_options = target.cards(return_places=True)
        if card_options:
            options.append(f"交给{player}一张牌，然后代替{player}成为对{target0}使用的{ctype.__name__}的使用者")
        if target.agent().choose(options, use_skill_event, f"请选择如何响应{player}的技能{self}"):
            place, card = card_options[target.agent().choose(card_options, use_skill_event, f"请选择要交给{player}的牌")]
            if place[0] == "手":
                print(f"{target}将一张手牌交给了{player}")
            else:
                print(f"{target}将{place}{card}交给了{player}")
            game.lose_card(target, card, place[0], "获得", use_skill_event)
            player.hand.append(card)
            print(f"{target}对{target0}使用了{ctype.__name__}")
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            for card in cards:
                game.lose_card(player, card, "手", "使用", cost_event)
            game.table.extend(cards)
            ctype.effect(target, cards, [target0])
            raise core.NoOptions
        else:
            print(f"{target}成为了{player}使用的卡牌{ctype.__name__}的额外目标")
            data.append(target)
            return data


class 骄矜(Skill):
    """
    当你受到男性角色造成的伤害时，你可以弃置一张装备牌，然后此伤害-1。
    """

    def can_use(self, player, event):  # 受到伤害时 <- damage
        return player is self.owner and event.who is player and event.what == "受到伤害时" and \
               event.cause.who and event.cause.who.male and player.cards(types=C_("装备牌"))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if data <= 0 or not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(types=C_("装备牌"), return_places=True)
        place, card = options[player.agent().choose(options, cost_event, "请选择要弃置的装备牌")]
        print(f"{player}发动了技能{self}，弃置了{place}{card}，令伤害-1")
        game.lose_card(player, card, place[0], "弃置", cost_event)
        game.table.append(card)
        return data - 1


class 诱敌(Skill):
    """
    出牌阶段限一次，你可以令一名其他角色弃置你的一张手牌，若弃置牌不为【杀】，你获得其一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and player.hand

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self)
        players = [p for p in game.iterate_live_players() if p is not player]
        target = players[player.agent().choose(players, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}对{target}发动了技能{self}")
        use_skill_event.targets = [target]
        card = random.choice(player.hand)
        print(f"{target}弃置了{player}的手牌{card}")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        game.lose_card(player, card, "手", "弃置", cost_event)
        game.table.append(card)
        if not issubclass(card.type, C_("杀")) and target.total_cards() > 0:
            place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择要获得的{target}的牌")
            if place[0] == "手":
                print(f"{player}获得了{target}的一张手牌")
            else:
                print(f"{player}获得了{target}{place}{card}")
            game.lose_card(target, card, place[0], "获得", use_skill_event)
            player.hand.append(card)
        self.use_quota -= 1


class 邀名(Skill):
    """
    每回合每个选项限一次，当你造成或受到伤害后，你可以选择一项：
    1. 弃置手牌数大于你的一名角色的一张手牌；
    2. 令手牌数小于你的一名角色摸一张牌；
    3. 令手牌数与你相同的一名角色弃置至多两张牌然后摸等量的牌。
    """
    options_dict = {1: "弃置手牌数大于你的一名角色的一张手牌",
                    2: "令手牌数小于你的一名角色摸一张牌",
                    3: "令手牌数与你相同的一名角色弃置至多两张牌然后摸等量的牌"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.skill_options = {1, 2, 3}

    def can_use(self, player, event):  # 造成伤害后/受到伤害后 <- damage
        if player is not self.owner:
            return False
        if event.what == "turn_start":
            return True
        elif event.what in ["造成伤害后", "受到伤害后"]:
            return event.who is player and self.skill_options
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.skill_options = {1, 2, 3}
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        i_options = list(self.skill_options)
        options = [self.options_dict[i] for i in i_options]
        i_chosen = i_options[player.agent().choose(options, use_skill_event, "请选择")]
        n_hand = len(player.hand)
        if i_chosen == 1:  # 弃置手牌数大于你的一名角色的一张手牌
            options = [p for p in game.iterate_live_players() if len(p.hand) > n_hand]
            if not options:
                return
            target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
            card = random.choice(target.hand)
            print(f"{player}对{target}发动了技能{self}")
            print(f"{player}弃置了{target}的手牌{card}")
            game.lose_card(target, card, "手", "弃置", use_skill_event)
            game.table.append(card)
        elif i_chosen == 2:  # 令手牌数小于你的一名角色摸一张牌
            options = [p for p in game.iterate_live_players() if len(p.hand) < n_hand]
            if not options:
                return
            target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
            print(f"{player}对{target}发动了技能{self}")
            game.deal_cards(target, 1)
        else:  # 令手牌数与你相同的一名角色弃置至多两张牌然后摸等量的牌
            options = [p for p in game.iterate_live_players() if len(p.hand) == n_hand]
            if not options:
                return
            target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
            print(f"{player}对{target}发动了技能{self}")
            n = target.discard_n_cards((0, 2), use_skill_event)
            if n > 0:
                game.deal_cards(target, n)
        self.skill_options.remove(i_chosen)


class 安国(Skill):
    """
    出牌阶段限一次，你可以选择其他角色装备区的一张牌并令其获得之，然后若其攻击范围内的角色因此而变少，则你摸一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p is not player and p.装备区]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "turn_start" or
                event.what == "play" and self.use_quota > 0 and len(self.legal_targets(player)) > 0)

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        self.use_quota -= 1
        game = player.game
        use_skill_event = UseSkillEvent(player, self)
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动{self}的目标")]
        use_skill_event.targets = [target]
        n_old = len([p for p in game.iterate_live_players() if game.can_attack(target, p)])
        options = target.cards("装")
        card = options[player.agent().choose(options, use_skill_event, f"请选择{target}装备区的一张牌")]
        print(f"{player}对{target}发动了技能{self}，令其将装备区的牌{card}收为手牌")
        game.lose_card(target, card, "装", "获得", use_skill_event)
        target.hand.append(card)
        n_new = len([p for p in game.iterate_live_players() if game.can_attack(target, p)])
        if n_new < n_old:
            game.deal_cards(player, 1)


class 傲才(Skill):
    """
    当你于回合外需要使用或打出基本牌时，你可以观看牌堆顶的两张牌并可以使用或打出需要的一张基本牌。
    """

    def can_use(self, player, event):  # pre_card_asked(player) <- card_asked(player, 闪)
        game = player.game
        if not (player is self.owner and event.who is player and event.what == "pre_card_asked"
                and player is not game.current_player()):
            return False
        ctype = event.cause.args["card_type"]
        if issubclass(type(ctype), tuple):
            for t in ctype:
                if issubclass(t, C_("基本牌")):
                    return True
            return False
        return issubclass(ctype, C_("基本牌"))

    def use(self, player, event, data=None):
        ctype, cards = data
        if ctype:
            return data
        game = player.game
        use_skill_event = UseSkillEvent(player, self, None, event)
        ctype = event.cause.args["card_type"]
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            cards = [game.draw_from_deck() for _ in range(2)]
            # print(f"{player}发动了技能{self}，观看了牌堆顶的两张牌{cards[0]}、{cards[1]}")
            print(f"{player}发动了技能{self}，观看了牌堆顶的两张牌")
            game.view_cards(player, cards, use_skill_event)
            options = [card for card in cards if issubclass(card.type, ctype)]
            if options:
                options = [None] + options
                card = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}使用或打出的基本牌")]
                if card is not None:
                    verb = event.cause.args["verb"]
                    print(f"{player}发动技能{self}，{verb}了{card}")
                    cards.remove(card)
                    game.deck = game.deck + cards
                    game.table.append(card)
                    return card.type, [card]
            game.deck = game.deck + cards[::-1]
        return None, []


class 黩武(Skill):
    """
    出牌阶段，你可以选择你攻击范围内的一名其他角色并弃置X张牌（X为该角色的体力值），然后对其造成1点伤害。
    若该角色因此进入濒死状态，则你失去1点体力，且此技能失效直到回合结束。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.disabled = False

    def legal_targets(self, player):
        game = player.game
        n = player.total_cards("手装")
        return [p for p in game.iterate_live_players()
                if p is not player and p.hp <= n and game.distance(player, p) <= player.attack_range()]

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "play":
            return event.who is player and not self.disabled and self.legal_targets(player)
        if event.what == "dying" and event.cause.what == "damage":  # dying <- damage <- use_skill
            event0 = event.cause.cause
            return event0.who is player and event0.what == "use_skill" and event0.skill is self
        if event.what == "turn_end":
            return event.who is player
        return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        if event.what == "dying":
            game.lose_health(player, 1, cost_event)
            self.disabled = True
            return
        if event.what == "turn_end":
            self.disabled = False
            return
        # event.what == "play"
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, f"请指定发动技能{self}的目标")]
        print(f"{player}对{target}发动了技能{self}")
        player.discard_n_cards(target.hp, cost_event)
        game.damage(target, 1, player, use_skill_event)


# ======= 群 =======
class 雄异(Skill):
    """
    限定技，出牌阶段，你可以令你和至多三名其他角色各摸三张牌。若你选择的其他角色的数量不大于一，则你回复1点体力。
    """

    labels = {"限定技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "play" and not self.used

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        options = [p for p in game.iterate_live_players() if p is not player]
        targets = [options[i] for i in
                   player.agent().choose_many(options, (0, 3), use_skill_event, "请选择除你以外的至多三名目标角色")]
        targets = set([player] + targets)
        print(f"{player}发动了技能{self}，令{'、'.join(str(p) for p in targets)}各摸三张牌")
        for p in game.iterate_live_players():
            if p in targets:
                game.deal_cards(p, 3)
        if len(targets) <= 2:
            game.recover(player, 1, use_skill_event)
        self.used = True


class 名士(Skill):
    """
    锁定技，当你受到伤害时，若伤害来源的装备区的牌的数量小于2，此伤害-1。
    """

    def can_use(self, player, event):  # 受到伤害时 <- damage
        return player is self.owner and event.who is player and event.what == "受到伤害时" and \
               event.cause.who is not None and len(event.cause.who.装备区) < 2

    def use(self, player, event, data=None):
        if data <= 0:
            return data
        print(f"{player}的技能{self}被触发，伤害-1")
        return data - 1


class 礼让(Skill):
    """
    当你的牌因弃置而置入弃牌堆后，你可以将其中的任意张牌交给其他角色。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "弃牌阶段"
        # TODO: Discard in cases other than 弃牌阶段

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        options = [p for p in game.iterate_live_players() if p is not player]
        while data and player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            cards = [data[i] for i in player.agent().choose_many(data, (1, len(data)), use_skill_event, "请选择任意张牌")]
            target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
            print(f"{player}发动了技能{self}，将{'、'.join(str(c) for c in cards)}交给了{target}")
            data = [card for card in data if card not in cards]
            target.hand.extend(cards)
        return data


class 双刃(Skill):
    """
    出牌阶段开始时，你可以与一名其他角色拼点：若你赢，你视为对一名其他角色使用一张【杀】（不计次数）；若你没赢，你结束出牌阶段。
    """

    def can_use(self, player, event):
        game = player.game
        return player is self.owner and event.who is player and event.what == "test_skip_phase" and \
               event.args["phase"] == "出牌阶段" and "出牌阶段" not in game.skipped and player.hand

    def use(self, player, event, data=None):
        game = player.game
        options = [p for p in game.iterate_live_players() if p is not player and p.hand]
        use_skill_event = UseSkillEvent(player, self, [], cause=event)
        if not options or not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}拼点的目标角色")]
        print(f"{player}发动了技能{self}，与{target}进行拼点")
        use_skill_event.targets = [target]
        winner, _, _ = game.拼点(player, target, use_skill_event)
        if winner is player:
            options = [p for p in game.iterate_live_players() if p is not player]
            target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}杀的目标（无视距离）")]
            print(f"{player}视为对{target}使用了一张杀")
            C_("杀").effect(player, [], [target])
            game.attack_quota += 1  # The 杀 is not supposed to count in terms of attack quota, so add it back
        else:
            game.skipped.add("出牌阶段")


class 死谏(Skill):
    """
    当你失去最后的手牌时，你可以弃置一名其他角色的一张牌。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.who is player and event.what == "lose_card" and
                event.zone == "手" and not player.hand)

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        options = [p for p in game.iterate_live_players() if p.total_cards() > 0]
        if options and player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
            place, card = game.pick_card(player, target, "手装", use_skill_event, "请选择要弃置的牌")
            print(f"{player}发动了技能{self}，弃置了{target}{place}{card}")
            game.lose_card(target, card, place[0], "弃置", use_skill_event)
            game.table.append(card)


class 随势(Skill):
    """
    锁定技，当其他角色因受到伤害而进入濒死状态时，若伤害来源与你势力相同，你摸一张牌；当其他角色死亡时，若其与你势力相同，你失去1点体力。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is not player):
            return False
        if event.what == "dying":  # dying <- damage
            event0 = event.cause
            return event0.what == "damage" and event0.who is not None and event0.who.faction == player.faction
        elif event.what == "die":
            return event.who.faction == player.faction
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        print(f"{player}的技能{self}被触发")
        if event.what == "dying":
            game.deal_cards(player, 1)
        else:  # event.what == "die"
            game.lose_health(player, 1, use_skill_event)


class 狂斧(Skill):
    """
    当你的【杀】对目标角色造成伤害后，你可以获得其装备区的一张牌。
    """

    def can_use(self, player, event):  # 造成伤害后 <- damage <- use_card
        if not (player is self.owner and event.who is player and event.what == "造成伤害后"):
            return False
        event0 = event.cause.cause
        return event0.who is player and event0.what == "use_card" and issubclass(event0.card_type, C_("杀")) \
               and event.cause.whom.装备区

    def use(self, player, event, data=None):
        game = player.game
        target = event.cause.whom
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否对{target}发动技能{self}"):
            return
        _, card = game.pick_card(player, target, "装", use_skill_event, f"请选择要获取的装备区的牌")
        print(f"{player}发动了技能{self}，获得了{target}的装备区的牌{card}")
        game.lose_card(target, card, "装", "获得", use_skill_event)
        player.hand.append(card)


class 鸩毒(Skill):
    """
    其他角色出牌阶段开始时，你可以弃置一张手牌，视为该角色使用一张【酒】，然后你对其造成1点伤害。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is not player and event.what == "phase_start" and \
               event.args["phase"] == "出牌阶段" and player.hand

    def use(self, player, event, data=None):
        game = player.game
        target = event.who
        use_skill_event = UseSkillEvent(player, self, [target], cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        card = player.hand[player.agent().choose(player.hand, cost_event, "请选择弃置的手牌")]
        print(f"{player}发动了技能{self}，弃置了手牌{card}，视为{target}使用了一张酒")
        game.lose_card(player, card, "手", "弃置", cost_event)
        game.table.append(card)
        C_("酒").effect(target, [], [])
        game.damage(target, 1, player, use_skill_event)


class 戚乱(Skill):
    """
    一名角色的回合结束时，你每于此回合内杀死过一名其他角色，你便摸三张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.n_kills = 0

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "die":
            return event.cause.what == "damage" and event.cause.who is player
        elif event.what == "turn_end":
            return self.n_kills > 0
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.n_kills = 0
            return
        if event.what == "die":  # die <- damage
            self.n_kills += 1
            return
        # event.what == turn_end
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            game.deal_cards(player, 3 * self.n_kills)


class 庸肆(Skill):
    """
    锁定技，摸牌阶段，你多摸X张牌；回合结束阶段，你弃置X张牌（不足则全弃）（X为势力数）。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what in ["摸牌阶段", "turn_end"]

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        n = len({p.faction for p in game.iterate_live_players()})
        if event.what == "摸牌阶段":
            print(f"{player}的技能{self}被触发，{player}额外摸{n}张牌")
            return data + n
        # event.what == "turn_end"
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        print(f"{player}的技能{self}被触发")
        player.discard_n_cards(n, cost_event)


class 伪帝(Skill):
    """
    锁定技，你视为拥有主公的主公技。
    """


class 耀武(Skill):
    """
    锁定技，当一名角色使用红色【杀】对你造成伤害时，该角色回复1点体力或摸一张牌。
    """

    def can_use(self, player, event):  # 造成伤害时 <- damage <- use_card
        if not (event.who is player and event.what == "造成伤害时" and event.cause.whom is self.owner):
            return False
        event0 = event.cause.cause
        return event0.what == "use_card" and issubclass(event0.card_type, C_("杀")) and core.color(event0.cards) == "red"

    def use(self, player, event, data=None):
        game = player.game
        target = event.cause.whom
        use_skill_event = UseSkillEvent(player, self, [target], event)
        print(f"{self.owner}的技能{self}被触发")
        options = ["摸一张牌"]
        if player.is_wounded():
            options.append("回复1点体力")
        if player.agent().choose(options, use_skill_event, "请选择"):
            game.recover(player, 1, use_skill_event)
        else:
            game.deal_cards(player, 1)
        return data


class 义从(Skill):
    """
    锁定技，你计算与其他角色的距离-X（X为你的体力值的一半，向下取整），其他角色计算与你的距离+Y（Y为你已损失的体力值的一半，向上取整）。
    """

    def can_use(self, player, event):
        return player is self.owner and event.what == "calc_distance" \
               and (event.who is player or event.args["to"] is player)

    def use(self, player, event, data=None):
        if event.who is player:
            n = player.hp // 2
            return data - n
        else:  # event.args["to"] is player
            n = -((player.hp - player.hp_cap) // 2)
            return data + n


class 明策(Skill):
    """
    出牌阶段限一次，你可以将一张装备牌或【杀】交给一名其他角色，然后其选择一项：视为对其攻击范围内你选择的另一名角色使用【杀】；摸一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or \
               event.what == "play" and self.use_quota > 0 and player.cards(types=(C_("杀"), C_("装备牌")))

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = [p for p in game.iterate_live_players() if p is not player]
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标角色")]
        options = player.cards(types=(C_("杀"), C_("装备牌")), return_places=True)
        place, card = options[player.agent().choose(options, cost_event, f"请选择一张装备牌或【杀】交给{target}")]
        print(f"{player}发动了技能{self}，将{place}{card}交给了{target}")
        game.lose_card(player, card, place[0], "获得", cost_event)
        target.hand.append(card)
        options = ["摸一张牌"]
        attack_options = [p for p in game.iterate_live_players() if game.can_attack(target, p)]
        target2 = None
        if attack_options:
            target2 = attack_options[player.agent().choose(attack_options, use_skill_event,
                                                           f"请选择令{target}对哪名角色视为使用【杀】")]
            print(f"{player}令{target}选择摸一张牌或视为对{target2}使用【杀】")
            options.append(f"视为对{target2}使用【杀】")
        if target.agent().choose(options, use_skill_event, "请选择"):
            print(f"{target}对{target2}使用了杀")
            C_("杀").effect(target, [], [target2])
        else:
            game.deal_cards(target, 1)
        self.use_quota -= 1


class 智迟(Skill):
    """
    锁定技，当你于回合外受到伤害后，本回合【杀】和普通锦囊牌对你无效。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = False

    def can_use(self, player, event):
        if player is not self.owner or player.game.current_player() is player:
            return False
        if event.what == "受到伤害后":
            return event.who is player
        elif event.what == "test_card_nullify":  # test_card_nullify <- use_card
            return event.who is player and self.buff and issubclass(event.cause.card_type, (C_("杀"), C_("即时锦囊")))
        elif event.what == "turn_end":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "受到伤害后":
            print(f"{player}的技能{self}被触发")
            self.buff = True
            return
        elif event.what == "test_card_nullify":
            print(f"{player}的技能{self}被触发，{event.cause.card_type.__name__}对{player}无效")
            return True
        else:  # event.what == "turn_end"
            self.buff = False
            return


class 陷阵(Skill):
    """
    出牌阶段限一次，你可以与一名角色拼点。若你赢，本回合你无视该角色的防具，且对该角色使用牌没有距离和次数限制；若你没赢，本回合你不能使用【杀】。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = None
        self.victim = None

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p is not player and p.hand]

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.who is not player:
            return event.what == "test_armor_disabled" and self.buff == "good" and event.who is self.victim
        if event.what == "play":  # Do 拼点 or use 杀 on victim
            return not self.buff and len(player.hand) > 0 and self.legal_targets(player) or self.buff == "good"
        elif event.what == "calc_distance":
            return self.buff == "good" and event.args["to"] is self.victim
        elif event.what == "use_card":
            return issubclass(event.card_type, C_("杀")) and len(event.targets) == 1 and event.targets[0] is self.victim
        elif event.what == "test_use_prohibited":
            return self.buff == "bad" and issubclass(event.args["card_type"], C_("杀"))
        elif event.what == "turn_end":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "test_armor_disabled":
            return True
        elif event.what == "calc_distance":
            return 1
        elif event.what == "use_card":
            print(f"{player}的技能{self}被触发，对{self.victim}使用【杀】无次数限制")
            game.attack_quota += 1
            return
        elif event.what == "test_use_prohibited":
            return True
        elif event.what == "turn_end":
            self.buff = None
            self.victim = None
            return
        # event.what == "play"
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not self.buff:  # Do 拼点
            options = self.legal_targets(player)
            target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
            print(f"{player}对{target}发动了技能{self}")
            use_skill_event.targets = [target]
            winner, _, _ = game.拼点(player, target, use_skill_event)
            if winner is player:
                self.buff = "good"
                self.victim = target
            else:
                self.buff = "bad"
        else:  # Use 杀
            ...  # TODO


class 禁酒(Skill):
    """
    锁定技，你的【酒】视为【杀】。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        wine = C_("酒")
        if event.what == "test_use_prohibited":
            cards = event.args["cards"]
            return len(cards) == 1 and issubclass(cards[0].type, wine) and issubclass(event.args["card_type"], wine)
        elif event.what == "test_respond_disabled":  # test_respond_disabled <- card_asked
            return issubclass(event.cause.args["card_type"], wine)
        if not player.cards(types=wine):
            return False
        return (event.what == "play" and C_("杀").can_use(player, []) or
                event.what == "card_asked" and issubclass(C_("杀"), event.args["card_type"]))

    # TODO: prohibit using ♥ cards for response

    def use(self, player, event, data=None):
        if event.what == "test_use_prohibited":
            return True
        elif event.what == "test_respond_disabled":
            return True
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(types=C_("酒"))
        card = options[player.agent().choose(options, cost_event, "请选择")]
        ctype = C_("杀")
        if event.what == "card_asked":
            game.lose_card(player, card, "手", "打出", cost_event)
            game.table.append(card)
            print(f"{player}发动了技能{self}，将{card}当杀打出")
            return ctype, [card]
        # event.what == "play"
        try:
            if not ctype.can_use(player, [card]):
                raise core.NoOptions
            args = ctype.get_args(player, [card])
        except core.NoOptions:
            print(f"{player}想要使用杀，但中途取消")
            return
        game.lose_card(player, card, "手", "使用", cost_event)
        game.table.append(card)
        print(f"{player}发动了技能{self}，将{card}当杀对{'、'.join(str(target) for target in args)}使用")
        ctype.effect(player, [card], args)


class 自守(Skill):
    """
    摸牌阶段，你可以额外摸X张牌（X为你已损失的体力值），然后本回合你不能对其他角色使用牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = False

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "摸牌阶段":
            return event.who is player and player.is_wounded()
        elif event.what == "test_target_prohibited":  # test_target_prohibited <- use_card
            return event.who is not player and self.buff and event.cause.who is player
        elif event.what == "turn_end":
            return event.who is player
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "摸牌阶段":
            use_skill_event = UseSkillEvent(player, self, cause=event)
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                n = player.hp_cap - player.hp
                print(f"{player}发动了技能{self}，额外摸{n}张牌")
                self.buff = True
                return data + n
            else:
                return data
        elif event.what == "test_target_prohibited":
            return True
        else:  # event.what == "turn_end"
            self.buff = False
            return


class 宗室(Skill):
    """
    锁定技，你的手牌上限+X（X为全场势力数）。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "calc_max_hand"

    def use(self, player, event, data=None):
        game = player.game
        n = len({p.faction for p in game.iterate_live_players()})
        print(f"{player}的技能{self}被触发，手牌上限+{n}")
        return data + n


class 惴恐(Skill):
    """
    其他角色的回合开始时，若你已受伤，你可以与其拼点：若你赢，本回合该角色只能对自己使用牌；若你没赢，本回合其与你的距离视为1。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = None
        self.victim = None

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "turn_start":
            return event.who is not player and player.is_wounded() and player.hand and event.who.hand
        elif event.what == "test_target_prohibited":  # test_target_prohibited <- use_card
            return self.buff == "good" and event.who is not self.victim and event.cause.who is self.victim
        elif event.what == "calc_distance":
            return self.buff == "bad" and event.who is self.victim and event.args["to"] is player
        elif event.what == "turn_end":
            return event.who is self.victim
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "test_target_prohibited":
            return True
        elif event.what == "calc_distance":
            return 1
        elif event.what == "turn_end":
            self.buff = None
            self.victim = None
            return
        # event.what == "turn_start"
        game = player.game
        use_skill_event = UseSkillEvent(player, self)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        target = event.who
        print(f"{player}对{target}发动了技能{self}")
        use_skill_event.targets = [target]
        self.victim = target
        winner, _, _ = game.拼点(player, target, use_skill_event)
        if winner is player:
            self.buff = "good"
        else:
            self.buff = "bad"


class 求援(Skill):
    """
    当你成为【杀】的目标时，你可以令另一名其他角色交给你一张【闪】，否则也成为此【杀】的目标。
    """

    def legal_targets(self, player, attacker):
        game = player.game
        return [p for p in game.iterate_live_players() if p is not attacker and p is not player]

    def can_use(self, player, event):  # confirm_targets <- use_card
        if not (player is self.owner and event.what == "confirm_targets"):
            return False
        event0 = event.cause
        if not (event0.what == "use_card" and issubclass(event0.card_type, C_("杀")) and player in event0.targets):
            return False
        return len(self.legal_targets(player, event0.who)) > 0

    def use(self, player, event, data=None):
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        game = player.game
        options = self.legal_targets(player, event.cause.who)
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动{self}的目标")]
        use_skill_event.targets = [target]
        print(f"{player}对{target}发动了技能{self}")
        options = ["也成为此杀的目标"]
        card_options = target.cards(types=C_("闪"))
        if card_options:
            options.append(f"交给{player}一张闪")
        if target.agent().choose(options, use_skill_event, f"请选择如何响应{player}的技能{self}"):
            card = card_options[target.agent().choose(card_options, use_skill_event, f"请选择要交给{player}的闪")]
            print(f"{target}将手牌{card}交给了{player}")
            game.lose_card(target, card, "手", "获得", use_skill_event)
            player.hand.append(card)
        else:
            print(f"{target}也成为了{player}杀的目标")
            data.append(target)
        return data


class 绝策(Skill):
    """
    结束阶段，你可以对一名没有手牌的其他角色造成1点伤害。
    """

    def legal_targets(self, player):
        game = player.game
        return [p for p in game.iterate_live_players() if p is not player and not p.hand]

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_end" and self.legal_targets(player)

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
        print(f"{player}对{target}发动了技能{self}")
        use_skill_event.targets = [target]
        game.damage(target, 1, player, use_skill_event)


class 灭计(Skill):
    """
    你使用黑色非延时类锦囊牌仅指定一个目标后，可以额外指定一个目标。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "modify_n_targets" and \
               issubclass(event.args["card_type"], C_("即时锦囊")) and core.color(event.args["cards"]) == "black"

    def use(self, player, event, data=None):
        if data == 1:
            print(f"{player}的技能{self}被触发，可额外指定一个目标")
            return data + 1
        else:
            return data


class 焚城(Skill):
    """
    限定技，出牌阶段，你可令所有其他角色依次选择一项：弃置X张牌;或受到1点火焰伤害。(X为该角色装备区里牌的数量且至少为1)
    """

    labels = {"限定技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "play" and not self.used

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        print(f"{player}发动了技能{self}")
        for target in game.iterate_live_players():
            if target is player:
                continue
            options = ["受到1点火焰伤害"]
            n = target.total_cards("装")
            if n == 0:
                n = 1
            if target.total_cards() >= n:
                options.append(f"弃置{n}张牌")
            if target.agent().choose(options, use_skill_event, "请选择"):
                target.discard_n_cards(n, use_skill_event)
            else:
                game.damage(target, 1, player, use_skill_event, "火")
        self.used = True


class 窃听(Skill):
    """
    其他角色的回合结束时，若其于此回合内没有对除其外的角色使用过牌，则你可以选择一项：1. 将其装备区里的一张牌放入你的装备区；2. 摸一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.cool = True

    def can_use(self, player, event):
        if player is not self.owner or event.who is player:
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "use_card":
            return event.who is player.game.current_player() and [p for p in event.targets if p is not event.who]
        elif event.what == "turn_end":
            return self.cool
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.cool = True
        elif event.what == "use_card":
            self.cool = False
        else:  # event.what == "turn_end"
            game = player.game
            use_skill_event = UseSkillEvent(player, self, cause=event)
            if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}")
                options = ["摸一张牌"]
                target = event.who
                card_options = [(key, card) for key, card in target.装备区.items() if key not in player.装备区]
                if card_options:
                    options.append(f"将{target}装备区里的一张牌放入你的装备区")
                if player.agent().choose(options, use_skill_event, "请选择"):
                    key, card = card_options[player.agent().choose(card_options, use_skill_event,
                                                                   f"请选择{target}装备区的一张牌")]
                    print(f"{player}将{target}装备区的牌{card}放入了自己的装备区")
                    game.lose_card(target, card, "装", "置于", use_skill_event)
                    player.装备区[key] = card
                else:
                    game.deal_cards(player, 1)


class 献州(Skill):
    """
    限定技，出牌阶段，你可以将装备区里的所有牌交给一名其他角色，然后该角色选择一项：
    1. 令你回复X点体力；
    2. 对其攻击范围内的至多X名角色各造成1点伤害（X为你以此法交给该角色的牌的数量）。
    """

    labels = {"限定技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "play" and not self.used and player.装备区

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        options = [p for p in game.iterate_live_players() if p is not player]
        target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
        cards = player.cards("装")
        print(f"{player}发动了技能{self}，将装备区的牌{'、'.join(str(c) for c in cards)}交给了{target}")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        for card in cards:
            game.lose_card(player, card, "装", "获得", cost_event)
        target.hand.extend(cards)
        n = len(cards)
        n_recover = min(n, player.hp_cap - player.hp)
        options = [f"对你攻击范围内的至多{n}名角色各造成1点伤害"]
        if n_recover > 0:
            options.append(f"令{player}回复{n_recover}点体力")
        if target.agent().choose(options, use_skill_event, "请选择"):
            game.recover(player, n_recover, use_skill_event)
        else:
            options = [p for p in game.iterate_live_players() if game.can_attack(target, p)]
            victims = [options[i] for i in
                       target.agent().choose_many(options, (0, n), use_skill_event, "请选择受到伤害的目标")]
            for victim in victims:
                game.damage(victim, 1, target, use_skill_event)
        self.used = True


class 渐营(Skill):
    """
    当你于出牌阶段内使用牌时，若此牌与你于此阶段内使用的上一张牌点数或花色相同，则你可以摸一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.last_suit = None
        self.last_rank = None

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what in ["turn_start", "use_card"]

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.last_suit = None
            self.last_rank = None
            return
        # event.what == "use_card"
        if len(event.cards) == 1:
            card = event.cards[0]
            this_suit = card.suit
            this_rank = card.rank
        else:
            this_suit = ""
            this_rank = 0
        if this_suit == self.last_suit or this_rank == self.last_rank:
            use_skill_event = UseSkillEvent(player, self, cause=event)
            if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}")
                player.game.deal_cards(player, 1)
        self.last_suit = this_suit
        self.last_rank = this_rank


class 矢北(Skill):
    """
    锁定技，你每回合第一次受到伤害后，回复1点体力。然后本回合每次受到伤害后均失去1点体力。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.damage_count = 0

    def can_use(self, player, event):  # 受到伤害后 <- damage
        if player is not self.owner:
            return False
        return event.who is player and event.what == "受到伤害后" or event.what == "turn_start"

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.damage_count = 0
            return data
        # event.what == "受到伤害后"
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        self.damage_count += 1
        print(f"{player}的技能{self}被触发")
        if self.damage_count == 1:
            game.recover(player, 1, use_skill_event)
        else:
            game.lose_health(player, 1, use_skill_event)


class 怀异(Skill):
    """
    出牌阶段限一次，你可以展示所有手牌，若不为同一颜色，则你弃置其中一种颜色的牌，然后获得至多X名其他角色的各一张牌（X为你以此法弃置的手牌数），
    若你获得的牌大于一张，则你失去1点体力。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and player.hand

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        print(f"{player}发动了技能{self}，展示了手牌{'、'.join(str(c) for c in player.hand)}")
        if core.color(player.hand) == "no_color":
            if player.agent().choose(["红", "黑"], use_skill_event, "请选择一种颜色，弃置该颜色的所有手牌"):
                suits = "♠♣"
            else:
                suits = "♥♦"
            to_discard = player.cards("手", suits=suits)
            print(f"{player}弃置了手牌{'、'.join(str(c) for c in to_discard)}")
            for card in to_discard:
                game.lose_card(player, card, "手", "弃置", cost_event)
            game.table.extend(to_discard)
            options = [p for p in game.iterate_live_players() if p is not player and p.cards()]
            if options:
                targets = [options[i] for i in
                           player.agent().choose_many(options, (1, len(to_discard)), use_skill_event, "请选择目标角色")]
                for target in game.iterate_live_players():
                    if target not in targets:
                        continue
                    place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择要获得的{target}的牌")
                    if place[0] == "手":
                        print(f"{player}获得了{target}的一张手牌")
                    else:
                        print(f"{player}获得了{target}{place}{card}")
                    game.lose_card(target, card, place[0], "获得", use_skill_event)
                    player.hand.append(card)
                if len(targets) > 1:
                    print(f"{player}失去了1点体力")
                    game.lose_health(player, 1, cost_event)
        self.use_quota -= 1


class 急攻(Skill):
    """
    出牌阶段开始时，你可以摸两张牌，然后你本回合的手牌上限等于你此阶段造成的伤害值。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = False
        self.n_damage = 0

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "phase_start":
            return event.args["phase"] == "出牌阶段"
        elif event.what == "造成伤害后":
            return self.buff
        elif event.what == "calc_max_hand":
            return self.buff
        else:
            return False

    def use(self, player, event, data=None):
        if not player.is_alive():
            return data
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], cause=event)
        if event.what == "turn_start":
            self.buff = False
            self.n_damage = 0
        elif event.what == "phase_start":
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}发动了技能{self}")
                game.deal_cards(player, 2)
                self.buff = True
        elif event.what == "造成伤害后":
            self.n_damage += event.cause.n  # 造成伤害后 <- damage
        else:  # event.what == "calc_max_hand"
            print(f"{player}的技能{self}被触发，手牌上限变为{self.n_damage}")
            return self.n_damage


class 饰非(Skill):
    """
    当你需要使用或打出【闪】时，你可以令当前回合角色摸一张牌，然后若其手牌不是唯一最多，则你弃置一名最多的角色一张牌，视为你使用或打出一张【闪】。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.who is player and event.what == "pre_card_asked"
                and issubclass(C_("闪"), event.cause.args["card_type"]))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return data
        print(f"{player}发动了技能{self}")
        current_player = game.current_player()
        game.deal_cards(current_player, 1)
        max_hand = max(len(p.hand) for p in game.iterate_live_players())
        options = [p for p in game.iterate_live_players()
                   if p.total_cards() > 0 and len(p.hand) == max_hand and p is not current_player]
        if options:
            target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}弃牌的目标角色")]
            place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择要弃置的{target}的牌")
            print(f"{player}弃置了{target}的{place}{card}，视为打出一张闪")
            game.lose_card(target, card, place[0], "弃置", use_skill_event)
            game.table.append(card)
            return C_("闪"), []
        else:
            return None, []


class 谋溃(Skill):
    """
    当你使用【杀】指定一个目标后，你可以选择一项：1. 摸一张牌；2. 弃置该角色的一张牌。若如此做此【杀】被【闪】抵消，该角色弃置你的一张牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.victims = []

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "use_card":
            return issubclass(event.card_type, C_("杀"))
        elif event.what == "attack_dodged":
            return event.args["target"] in self.victims and player.total_cards() > 0
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "use_card":
            self.victims = []
            for target in event.targets:
                use_skill_event = UseSkillEvent(player, self, [target], event)
                if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                    continue
                print(f"{player}对{target}发动了技能{self}")
                self.victims.append(target)
                options = ["摸一张牌"]
                if target.total_cards() > 0:
                    options.append(f"弃置{target}的一张牌")
                if player.agent().choose(options, use_skill_event, "请选择"):
                    place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择要弃置的{target}的牌")
                    print(f"{player}弃置了{target}{place}{card}")
                    game.lose_card(target, card, place[0], "弃置", use_skill_event)
                    game.table.append(card)
                else:
                    game.deal_cards(player, 1)
            return
        # event.what == "attack_dodged"
        target = event.args["target"]
        use_skill_event = UseSkillEvent(player, self, [target], event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        self.victims.remove(target)
        place, card = game.pick_card(target, player, "手装", cost_event, f"请选择要弃置的{target}的牌")
        print(f"{target}弃置了{player}{place}{card}")
        game.lose_card(player, card, place[0], "弃置", cost_event)
        game.table.append(card)
        return data


class 天命(Skill):
    """
    当你成为【杀】的目标后，你可以先弃置两张牌（不足则全弃置）再摸两张牌，然后除你外体力值唯一最大的角色也可以如此做。
    """

    def can_use(self, player, event):
        return (player is self.owner and event.what == "use_card"
                and player in event.targets and issubclass(event.card_type, C_("杀")))

    def use(self, player, event, data=None):
        game = player.game
        users = [player]
        max_hp = max(p.hp for p in game.iterate_live_players() if p is not player)
        players = [p for p in game.iterate_live_players() if p is not player and p.hp == max_hp]
        if len(players) == 1:
            users.append(players[0])
        for user in users:
            use_skill_event = UseSkillEvent(user, self, [], event)
            cost_event = Event(user, "use_skill_cost", use_skill_event)
            if not user.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                return
            print(f"{user}发动了技能{self}")
            user.discard_n_cards(2, cost_event)
            game.deal_cards(user, 2)


class 密诏(Skill):
    """
    出牌阶段限一次，你可以将所有手牌交给一名其他角色，然后令该角色与你选择的另一名其他角色拼点，拼点赢的角色视为对拼点没赢的角色使用一张【杀】。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and len(player.hand) > 0

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.use_quota = 1
            return
        use_skill_event = UseSkillEvent(player, self)
        options = [p for p in game.iterate_live_players() if p is not player]
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标")]
        print(f"{player}对{target}发动了技能{self}，交给了{target}{len(player.hand)}张手牌")
        use_skill_event.targets = [target]
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        cards = player.cards("手")
        for card in cards:
            game.lose_card(player, card, "手", "获得", cost_event)
        target.hand.extend(cards)
        options = [p for p in game.iterate_live_players() if p not in [player, target] and p.hand]
        if not options:
            return
        target2 = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}令{target}与之拼点的目标")]
        print(f"{player}令{target}与{target2}拼点")
        winner, _, _ = game.拼点(target, target2, use_skill_event)
        if winner is target:
            loser = target2
        else:
            loser = target
        print(f"{winner}视为对{loser}使用杀")
        C_("杀").effect(winner, [], [loser])  # TODO: 流离, 短兵
        self.use_quota -= 1


class 义舍(Skill):
    """
    结束阶段，若你没有“米”，你可以摸两张牌，然后将两张牌置于武将牌上，称为“米”；当你移去最后一张“米”时，你回复1点体力。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_end":
            return not player.repo
        elif event.what == "lose_card":
            return event.zone == "库" and not player.repo

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "lose_card":
            game.recover(player, 1, use_skill_event)
            return
        # event.what == "turn_end"
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            game.deal_cards(player, 2)
            options = player.cards(return_places=True)
            place_card_tuples = [options[i] for i in
                                 player.agent().choose_many(options, 2, use_skill_event, "请选择两张牌置于武将牌上作为“米”")]
            print(f"{player}将{'、'.join(str(c) for _, c in place_card_tuples)}置于武将牌上作为“米”")
            for place, card in place_card_tuples:
                game.lose_card(player, card, place[0], "置于", use_skill_event)
                player.repo.append(card)


class 布施(Skill):
    """
    当你受到1点伤害后，你可以获得一张“米”；当你对其他角色造成伤害后，其可以获得一张“米”。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what in ["受到伤害后", "造成伤害后"] and player.repo

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "受到伤害后":
            n = event.cause.n
            for _ in range(n):
                if not player.repo:
                    break
                if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                    card = player.repo[player.agent().choose(player.repo, use_skill_event, "请选择要获得的“米”")]
                    print(f"{player}发动了技能{self}，获得了一张“米”（{card}）")
                    # player.repo.remove(card)
                    game.lose_card(player, card, "库", "置于", use_skill_event)
                    player.hand.append(card)
            return
        # event.what == "造成伤害后"
        target = event.cause.whom
        if not target.is_alive():
            return
        if target.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动{player}的技能{self}"):
            card = player.repo[target.agent().choose(player.repo, use_skill_event, "请选择要获得的“米”")]
            print(f"{target}发动了{player}的技能{self}，获得了一张“米”（{card}）")
            # player.repo.remove(card)
            game.lose_card(player, card, "库", "置于", use_skill_event)
            target.hand.append(card)


class 米道(Skill):
    """
    当一张判定牌生效前，你可以打出一张“米”代替之。
    """

    def can_use(self, player, event):
        return player is self.owner and event.what == "judge" and player.repo

    def use(self, player, event, data=None):
        game = player.game
        judgment = data
        use_skill_event = UseSkillEvent(player, self, [], event)
        options = ["pass"] + player.repo
        choice = player.agent().choose(options, use_skill_event, f"请选择是否发动技能{self}")
        if choice:
            card = options[choice]
            print(f"{player}发动了技能{self}，将判定牌改为{card}")
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            game.lose_card(player, card, "库", "打出", cost_event)
            game.table.append(judgment)  # Game.judge will add judge result to the table
            return card
        else:
            return judgment


## ======= DIY =======
class DIY忠勇(Skill):
    """
    你可以采用以下方式之一来视为使用或打出一张【杀】或【闪】：1. 弃一张装备牌，2. 失去1点体力。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return (event.what == "play" and C_("杀").can_use(player, []) or
                event.what == "card_asked" and issubclass(event.args["card_type"], (C_("杀"), C_("闪"))))

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = ["失去1点体力"]
        card_options = player.cards(types=C_("装备牌"), return_places=True)
        place, card = None, None
        if card_options:
            options.append("弃一张装备牌")
        if player.agent().choose(options, cost_event, "请选择"):
            place, card = card_options[player.agent().choose(card_options, cost_event, "请选择要弃置的装备牌")]
        if event.what == "card_asked":
            ctype = event.args["card_type"]
            verb = event.args["verb"]
            if card:
                print(f"{player}发动了技能{self}，弃置了{place}{card}，视为{verb}了一张{ctype.__name__}")
                game.lose_card(player, card, place[0], "弃置", cost_event)
                game.table.append(card)
            else:
                print(f"{player}发动了技能{self}，失去了1点体力，视为{verb}了一张{ctype.__name__}")
                game.lose_health(player, 1, cost_event)
            return ctype, []
        # event.what == "play"
        ctype = C_("杀")
        key = None
        if place and place[0] == "装":
            key = [k for k in player.装备区 if player.装备区[k] is card][0]
            player.remove_card(card)  # remove_card before get_args to avoid cases when using the card for 武圣 will make
            # the attack invalid (e.g. target becomes out of range, player no longer has attack quota (诸葛连弩), or the
            # number of targets is changed (方天画戟))
        try:
            if not ctype.can_use(player, []):
                raise core.NoOptions
            args = ctype.get_args(player, [])
        except core.NoOptions:
            print(f"{player}想要发动技能{self}，但中途取消")
            if key:
                player.装备区[key] = card
            return
        if key:
            player.装备区[key] = card
        print(f"{player}发动了技能{self}，视为对{'、'.join(str(p) for p in args)}使用了一张{ctype.__name__}")
        if card:
            print(f"{player}弃置了{place}{card}")
            game.lose_card(player, card, place[0], "弃置", cost_event)
            game.table.append(card)
        else:
            print(f"{player}失去了1点体力")
            game.lose_health(player, 1, cost_event)
        ctype.effect(player, [], args)


class 沉毅v1(Skill):
    """
    当你受到伤害后，你可以进行判定，若结果为♠或♣，你令一名角色摸X张牌（X为你已损失的体力值）；若结果为♦，你回复1点体力。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        return player is self.owner and event.who is player and event.what == "受到伤害后"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not (game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}")):
            return
        print(f"{player}发动了技能{self}")
        judgment = game.judge(player, use_skill_event)
        if judgment.suit == "♦":
            game.recover(player, 1, use_skill_event)
        elif judgment.suit in "♠♣":
            options = [p for p in game.iterate_live_players()]
            target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
            print(f"{player}令{target}摸牌")
            n = player.hp_cap - player.hp
            game.deal_cards(target, n)


class 沉毅v2(Skill):
    """
    当你受到伤害后，你可以进行判定，若结果不为♥，你令一名角色摸X张牌（X为你已损失的体力值）；若结果为♥，你回复1点体力。
    """

    def can_use(self, player, event):  # 受到伤害后 <- damage
        return player is self.owner and event.who is player and event.what == "受到伤害后"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not (game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}")):
            return
        print(f"{player}发动了技能{self}")
        judgment = game.judge(player, use_skill_event)
        if judgment.suit == "♥":
            game.recover(player, 1, use_skill_event)
        else:
            options = [p for p in game.iterate_live_players()]
            target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
            print(f"{player}令{target}摸牌")
            n = player.hp_cap - player.hp
            game.deal_cards(target, n)


沉毅 = 沉毅v2


class DIY恢拓v1(Skill):
    """
    出牌阶段限三次，你可以弃一张基本牌并亮出牌堆顶的三张牌，然后你可以获得其中的一张非基本牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 3

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "play":
            return self.use_quota > 0 and player.cards(types=C_("基本牌"))
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 3
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(types=C_("基本牌"))
        card = options[player.agent().choose(options, cost_event, "请选择要弃置的基本牌")]
        cards = [game.draw_from_deck() for _ in range(3)]
        print(f"{player}发动了技能{self}，弃置了手牌{card}，亮出了牌堆顶的3张牌：{'、'.join(str(c) for c in cards)}")
        self.use_quota -= 1
        game.lose_card(player, card, "手", "弃置", cost_event)
        game.table.append(card)
        options = [None] + [c for c in cards if c.type.class_ != "基本牌"]
        card = options[player.agent().choose(options, use_skill_event, "请选择要获得的非基本牌")]
        if card:
            print(f"{player}获得了{card}")
            cards.remove(card)
            player.hand.append(card)
        print(f"{'、'.join(str(c) for c in cards)}进入了弃牌堆")
        game.table.extend(cards)


class DIY恢拓v2(Skill):
    """
    出牌阶段，你可以弃一张基本牌（每回合每种花色的基本牌限一次）并亮出牌堆顶的四张牌，然后你可以获得其中的一张非基本牌。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.suits = set()

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "play":
            return player.cards(types=C_("基本牌"), suits=self.suits)
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.suits = set("♠♥♣♦")
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = player.cards(types=C_("基本牌"), suits=self.suits)
        card = options[player.agent().choose(options, cost_event, "请选择要弃置的基本牌")]
        cards = [game.draw_from_deck() for _ in range(4)]
        print(f"{player}发动了技能{self}，弃置了手牌{card}，亮出了牌堆顶的四张牌：{'、'.join(str(c) for c in cards)}")
        self.suits.remove(card.suit)
        game.lose_card(player, card, "手", "弃置", cost_event)
        game.table.append(card)
        options = [None] + [c for c in cards if c.type.class_ != "基本牌"]
        card = options[player.agent().choose(options, use_skill_event, "请选择要获得的非基本牌")]
        if card:
            print(f"{player}获得了{card}")
            cards.remove(card)
            player.hand.append(card)
        print(f"{'、'.join(str(c) for c in cards)}进入了弃牌堆")
        game.table.extend(cards)


DIY恢拓 = DIY恢拓v2


class 断识(Skill):
    """
    主公技，判定阶段开始时，其他魏势力角色可以弃一张手牌，然后弃置你判定区的一张牌。
    """

    labels = {"主公技"}

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "phase_start" and \
               event.args["phase"] == "判定阶段" and player.判定区

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if not (game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}")):
            return
        print(f"{player}发动了技能{self}")
        for p in game.iterate_live_players():
            if p.faction != "魏" or p is player or not p.hand:
                continue
            if not p.agent().choose(["不响应", "响应"], use_skill_event, f"请选择是否响应{player}的技能{self}"):
                continue
            cost_event = Event(p, "use_skill_cost", use_skill_event)
            card = p.hand[p.agent().choose(p.hand, cost_event, "请选择要弃置的手牌")]
            options = player.cards("判")
            card_judge = options[p.agent().choose(options, use_skill_event, f"请选择要弃置的{player}判定区的牌")]
            print(f"{p}响应了{player}的技能{self}，弃置了手牌{card}，并弃置了{player}判定区的牌{card_judge}")
            game.lose_card(p, card, "手", "弃置", cost_event)
            game.table.append(card)
            game.lose_card(player, card_judge, "判", "弃置", use_skill_event)
            game.table.append(card_judge)
            if not player.判定区:
                break


class DIY强识(Skill):
    """
    出牌阶段，你可以声明一张基本牌或非延时类锦囊牌的名称并指定一名有手牌的其他角色（每回合每种牌的名称限一次且每名角色限一次）。
    若该角色的手牌中有你所声明的牌，其需展示之（若有多张则展示其中一张），然后你可以立即将一张手牌当这种牌使用；
    若该角色的手牌中没有你所声明的牌，其需展示所有手牌，然后你本回合不能再次发动本技能。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = False
        self.card_types = set()
        self.targets = set()

    def legal_targets(self, player):
        return [p for p in player.game.iterate_live_players() if p is not player and p.hand and p not in self.targets]

    def card_type_options(self):
        card_types = ["杀", "火杀", "雷杀", "闪", "桃", "酒", "无懈可击", "南蛮入侵", "五谷丰登", "桃园结义", "万箭齐发",
                      "过河拆桥", "顺手牵羊", "无中生有", "决斗", "借刀杀人", "铁索连环", "火攻"]
        return [ctype for ctype in card_types if ctype not in self.card_types]

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "turn_start":
            return True
        elif event.what == "play":
            return not self.buff and self.legal_targets(player) and self.card_type_options()
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "turn_start":
            self.buff = False
            self.card_types = set()
            self.targets = set()
            return
        use_skill_event = UseSkillEvent(player, self, cause=event)
        options = self.card_type_options()
        ctype = options[player.agent().choose(options, use_skill_event, "请选择要声明的基本牌或即时锦囊牌的名称")]
        options = self.legal_targets(player)
        target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
        print(f"{player}对{target}发动了技能{self}，声明了卡牌：{ctype}")
        self.card_types.add(ctype)
        self.targets.add(target)
        ctype = C_(ctype)
        options = target.cards("手", types=ctype)
        if options:
            card = options[target.agent().choose(options, use_skill_event, f"请选择要展示的一张{ctype.__name__}")]
            print(f"{target}展示了手牌{card}")
            if not ctype.can_use(player, []) or not player.hand:
                return
            if not player.agent().choose(["不使用", "使用"], use_skill_event, f"请选择是否要将一张手牌当{ctype.__name__}使用"):
                return
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            options = player.cards("手")
            card = options[player.agent().choose(options, cost_event, f"请选择要当{ctype.__name__}使用的一张手牌")]
            try:
                args = ctype.get_args(player, [card])
            except core.NoOptions:
                print(f"{player}想要发动技能{self}将{card}当{ctype.__name__}使用，但中途取消")
                return
            print(f"{player}将{card}当{ctype.__name__}对{'、'.join(str(target) for target in args)}使用")
            game.lose_card(player, card, "手", "使用", cause=cost_event)
            game.table.append(card)
            ctype.effect(player, [card], args)
        else:
            print(f"{target}展示了所有手牌：{'、'.join(str(c) for c in target.hand)}")
            self.buff = True


class DIY献图(Skill):
    """
    其他角色的出牌阶段开始时，你可以交给其一张牌，然后若其交给你两张牌，其与所有与你距离为1的其他角色的距离变为1，直到回合结束。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.buff = False

    def can_use(self, player, event):
        if player is not self.owner or event.who is player:
            return False
        if event.what == "phase_start":
            return event.args["phase"] == "出牌阶段" and player.total_cards() > 0
        elif event.what == "calc_distance":
            game = player.game
            return self.buff and event.who is game.current_player() and game.distance(player, event.args["to"]) == 1
        elif event.what == "turn_end":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "calc_distance":
            return 1
        elif event.what == "turn_end":
            self.buff = False
            return
        # event.what == "phase_start"
        game = player.game
        target = event.who
        if not target.is_alive():
            return  # could be killed by 鸩毒
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        print(f"{player}发动了技能{self}")
        options = player.cards(return_places=True)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        place, card = options[player.agent().choose(options, cost_event, f"请选择要交给{target}的牌")]
        if place[0] == "手":
            print(f"{player}将一张手牌交给了{target}")
        else:
            print(f"{player}将{place}{card}交给了{target}")
        game.lose_card(player, card, place[0], "获得", cost_event)
        target.hand.append(card)
        options = target.cards(return_places=True)
        if len(options) < 2:
            return
        if not target.agent().choose(["否", "是"], use_skill_event,
                                     f"请选择是否交给{player}两张牌，使所有与其距离为1的其他角色与你的距离变为1"):
            return
        place_card_tuples = [options[i] for i in
                             target.agent().choose_many(options, 2, use_skill_event, f"请选择交给{player}的两张牌")]
        hand_cards = [card for place, card in place_card_tuples if place[0] == "手"]
        equip_cards = [card for place, card in place_card_tuples if place[0] == "装"]
        if hand_cards:
            print(f"{target}把{len(hand_cards)}张手牌交给了{player}")
        if equip_cards:
            print(f"{target}把装备区的牌{'、'.join(str(c) for c in equip_cards)}交给了{player}")
        for place, card in place_card_tuples:
            game.lose_card(target, card, place[0], "获得", use_skill_event)
            player.hand.append(card)
        targets = [p for p in game.iterate_live_players() if
                   game.distance(player, p) == 1 and game.distance(target, p) > 1]
        print(f"{target}与{'、'.join(str(p) for p in targets)}的距离变为1，直到回合结束")
        self.buff = True


class 水缚(Skill):
    """
    每当一名角色使用一张红色【杀】时，你可以弃一张牌令此【杀】具有以下效果：1. 若被【闪】响应，则使用者摸两张牌；2. 若造成伤害，则伤害+1。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_card_event = None

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "use_card":
            return issubclass(event.card_type, C_("杀")) and \
                   core.color(event.cards) == "red" and player.total_cards() > 0
        elif event.what == "attack_dodged":  # attack_dodged <- use_card
            return event.cause is self.use_card_event
        elif event.what == "造成伤害时":  # 造成伤害时 <- damage <- use_card
            return event.cause.cause is self.use_card_event
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if event.what == "use_card":
            if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                return
            print(f"{player}发动了技能{self}")
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            player.discard_n_cards(1, cost_event)
            self.use_card_event = event
            return
        elif event.what == "attack_dodged":
            print(f"{player}的技能{self}被触发")
            game.deal_cards(self.use_card_event.who, 2)
            return
        else:  # event.what == "造成伤害时"
            print(f"{player}的技能{self}被触发，伤害+1")
            return data + 1
        # TODO: The skill doesn't work now


class 决志(Skill):
    """
    锁定技，出牌阶段开始时，你失去1点体力，然后选择一项：1、摸两张牌；2、弃置一至两名其他角色的共计两张牌。你觉醒后，此技能改为非锁定技。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.awaken = False

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        if event.what == "phase_start":
            return event.args["phase"] == "出牌阶段"
        elif event.what == "wake":
            return True
        else:
            return False

    def use(self, player, event, data=None):
        if event.what == "wake":
            self.awaken = True
            return
        # event.what == "phase_start"
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [self.owner])
        if self.awaken and not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            return
        print(f"{player}发动了技能{self}，失去了1点体力")
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        game.lose_health(player, 1, cost_event)
        if not player.is_alive():
            return
        if player.agent().choose(["摸两张牌", "弃置一至两名其他角色的共计两张牌"], use_skill_event, "请选择"):
            for i in range(2):
                options = [p for p in game.iterate_live_players() if p is not player and p.total_cards() > 0]
                if not options:
                    break
                target = options[player.agent().choose(options, use_skill_event, "请选择目标角色")]
                place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择要弃置的{target}的牌")
                print(f"{player}弃置了{target}{place}{card}")
                game.lose_card(target, card, place[0], "弃置", use_skill_event)
                game.table.append(card)
        else:
            game.deal_cards(player, 2)


class 死孝(Skill):
    """
    觉醒技，当你进入濒死状态时，你减1点体力上限并将体力回复至2点，获得技能“仁德”，然后你在当前回合结束后进行一个额外的回合。
    """
    labels = {"觉醒技"}

    def __init__(self, owner=None):
        super().__init__(owner)
        self.used = False

    def can_use(self, player, event):
        if player is not self.owner:
            return False
        if event.what == "dying":
            return event.who is player and not self.used
        elif event.what == "after_turn_end":
            return self.used
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self)
        if event.what == "dying":
            print(f"{player}的技能{self}被触发，减了1点体力上限，并获得了技能“仁德”")
            self.used = True
            game.change_hp_cap(player, -1, use_skill_event)
            n_recover = 2 - player.hp
            game.recover(player, n_recover, use_skill_event)
            player.skills = player.skills[:]  # Avoid modifying the list when iterating through it
            new_skill = 仁德(player)
            player.skills.append(new_skill)
            game.trigger_skills(Event(player, "wake"))
        else:  # event.what == "after_turn_end"
            print(f"{player}的技能{self}被触发，进行一个额外的回合")
            player.skills = player.skills[:]  # Avoid modifying the list when iterating through it
            player.skills.remove(self)
            old_pid = game.current_pid
            game.current_pid = player.pid()
            game.run_turn()
            game.current_pid = old_pid


class 慷慨(Skill):
    """
    主公技，出牌阶段，你可以额外使用X张【杀】（X为其他蜀势力角色数）。
    """
    labels = {"主公技"}

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "phase_start" and \
               event.args["phase"] == "出牌阶段"

    def use(self, player, event, data=None):
        game = player.game
        n = len([p for p in game.iterate_live_players() if p is not player and p.faction == "蜀"])
        if n > 0:
            print(f"{player}技能{self}被触发，{player}可以额外使用{n}张杀")
            game.attack_quota += n


class 护前(Skill):
    """
    当一名其他角色成为你使用【杀】的目标，或对你使用【杀】时，若其手牌数大于你的手牌数，你可以弃置其一张牌。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.what == "use_card" and issubclass(event.card_type, C_("杀"))):
            return False
        return event.who is player or player in event.targets

    def use(self, player, event, data=None):
        game = player.game
        if event.who is player:
            targets = event.targets
        else:
            targets = [event.who]
        for target in targets:
            if target.total_cards("手") <= player.total_cards("手"):
                continue
            use_skill_event = UseSkillEvent(player, self, [target], event)
            if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
                print(f"{player}对{target}发动了技能{self}")
                place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择要弃置的一张{target}的牌")
                print(f"{player}弃置了{target}{place}{card}")
                game.lose_card(target, card, place[0], "弃置", use_skill_event)
                game.table.append(card)


class 兴教(Skill):
    """
    出牌阶段限一次，你可以选择至多X名角色（X为你的体力上限），令这些角色依次摸两张牌再将两张牌置于牌堆顶。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        # event.what == "play"
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        self.use_quota -= 1
        options = [p for p in game.iterate_live_players()]
        n = player.hp_cap
        targets = [options[i] for i in player.agent().choose_many(options, (1, n), use_skill_event, "请选择目标角色")]
        print(f"{player}对{'、'.join(str(p) for p in targets)}发动了技能{self}")
        for target in game.iterate_live_players():
            if target not in targets:
                continue
            game.deal_cards(target, 2)
            options = target.cards(return_places=True)
            place_card_tuples = [options[i] for i in
                                 target.agent().choose_many(options, 2, use_skill_event, "请选择要置于牌堆顶的两张牌")]
            equip_cards = [card for place, card in place_card_tuples if place[0] == "装"]
            if equip_cards:
                print(f"{target}将装备区的牌{'、'.join(str(c) for c in equip_cards)}置于牌堆顶")
            n_hand = len(place_card_tuples) - len(equip_cards)
            if n_hand > 0:
                print(f"{target}将{n_hand}张手牌置于牌堆顶")
            for place, card in place_card_tuples[::-1]:
                game.lose_card(target, card, place[0], "置于", use_skill_event)
                game.deck.append(card)


class 除奸(Skill):
    """
    出牌阶段限一次，你可以交给一名其他角色一张红色牌，然后弃置其一张牌。若你弃置的牌为♠花色，你对其造成1点伤害。
    """

    def __init__(self, owner=None):
        super().__init__(owner)
        self.use_quota = 1

    def can_use(self, player, event):
        if not (player is self.owner and event.who is player):
            return False
        return event.what == "turn_start" or event.what == "play" and self.use_quota > 0 and player.cards(suits="♥♦")

    def use(self, player, event, data=None):
        if event.what == "turn_start":
            self.use_quota = 1
            return
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        self.use_quota -= 1
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = [p for p in game.iterate_live_players() if p is not player]
        target = options[player.agent().choose(options, use_skill_event, f"请选择发动技能{self}的目标角色")]
        options = player.cards(suits="♥♦", return_places=True)
        place, card = options[player.agent().choose(options, cost_event, f"请选择交给{target}的红色牌")]
        print(f"{player}发动了技能{self}，将{place}{card}交给了{target}")
        game.lose_card(player, card, place[0], "获得", cost_event)
        target.hand.append(card)
        place, card = game.pick_card(player, target, "手装", use_skill_event, f"请选择要弃置的{target}的牌")
        print(f"{player}弃置了{target}{place}{card}")
        game.lose_card(target, card, place[0], "弃置", use_skill_event)
        game.table.append(card)
        if card.suit == "♠":
            game.damage(target, 1, player, use_skill_event)


class 守文(Skill):
    """
    主公技，摸牌阶段开始时，每名其他吴势力角色可以依次弃一张装备牌并令你选择一项：1、获得其弃置的装备牌；2、本阶段摸牌时多摸一张牌。
    """
    labels = {"主公技"}

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "摸牌阶段"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        targets = [p for p in game.iterate_live_players() if p is not player and p.faction == "吴" and p.total_cards()]
        if not targets or not \
                (game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}")):
            return data
        print(f"{player}发动了技能{self}")
        n_draw = 0
        for target in targets:
            options = target.cards(types=C_("装备牌"), return_places=True)
            if not options or not target.agent().choose(["不响应", "响应"], use_skill_event,
                                                        f"请选择是否响应{player}的技能{self}"):
                continue
            place, card = options[target.agent().choose(options, use_skill_event, "请选择要弃置的装备牌")]
            print(f"{target}响应了{player}的技能{self}，弃置了{place}{card}")
            game.lose_card(target, card, place[0], "弃置", use_skill_event)
            options = ["获得其弃置的装备牌", "摸牌阶段摸牌时多摸一张牌"]
            if player.agent().choose(options, use_skill_event, "请选择"):
                game.table.append(card)
                n_draw += 1
            else:
                print(f"{player}获得了{target}弃置的牌{card}")
                player.hand.append(card)
        return data + n_draw


class 受爵(Skill):
    """
    结束阶段开始时，你可以摸一张牌，然后将一张手牌置于你的武将牌上并盖住已有的牌，称为“爵”。
    你将你的势力变更为这张“爵”所对应的势力：♠群；♥蜀；♣魏；♦吴。
    """

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "turn_end"

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动技能{self}"):
            print(f"{player}发动了技能{self}")
            game.deal_cards(player, 1)
            options = player.hand
            cost_event = Event(player, "use_skill_cost", use_skill_event)
            card = options[player.agent().choose(options, cost_event, "请选择一张手牌置于武将牌上，作为“爵”")]
            faction_dict = {"♠": "群", "♥": "蜀", "♣": "魏", "♦": "吴"}
            faction = faction_dict[card.suit]
            print(f"{player}将手牌{card}置于武将牌上，并将势力变为{faction}")
            game.lose_card(player, card, "手", "置于", cost_event)
            player.repo.append(card)
            player.faction = faction


class 附势(Skill):
    """
    每当与你势力相同的角色使用【杀】造成伤害后，你可以摸一张牌。
    """

    def can_use(self, player, event):
        if not (player is self.owner and event.what == "造成伤害后"):
            return False
        event0 = event.cause.cause  # 造成伤害后 <- damage <- use_card
        return event0.what == "use_card" and issubclass(event0.card_type, C_("杀")) and \
               event0.who.faction == player.faction

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, [], event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动{self}"):
            print(f"{player}发动了技能{self}")
            game.deal_cards(player, 1)


class 自封(Skill):
    """
    觉醒技，准备阶段开始时，若你的“爵”不少于四张且不为同一花色，你增加1点体力上限，回复1点体力，获得所有的“爵”，然后失去技能“受爵”。
    """

    labels = {"觉醒技"}

    def can_use(self, player, event):
        return player is self.owner and event.who is player and event.what == "before_turn_start" \
               and len(player.repo) >= 4 and len(set(card.suit for card in player.repo)) > 1

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, event)
        print(f"{player}的技能{self}被触发，加了1点体力上限，并失去了技能“受爵”")
        game.change_hp_cap(player, 1, use_skill_event)
        game.recover(player, 1, use_skill_event)
        print(f"{player}获得了武将牌上的牌{'、'.join(str(c) for c in player.repo)}")
        player.hand.extend(player.repo)
        player.repo = []
        player.skills = player.skills[:]  # Avoid modifying the list when iterating through it in Game.trigger_skills()
        player.skills.remove(self)
        for skill in player.skills:
            if isinstance(skill, 受爵):
                player.skills.remove(skill)
        player.faction = player.character.faction  # Reset faction (which could have been changed by 受爵)
        game.trigger_skills(Event(player, "wake"))


def get_skill(name):
    if name[0] == '*':
        name = name[1:]
    try:
        skill_type = globals()[name]
        if not issubclass(skill_type, Skill):
            raise KeyError
        return skill_type
    except KeyError:
        return None
