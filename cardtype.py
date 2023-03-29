import random

import core
from core import CardType, Event, UseCardEvent, UseSkillEvent, Skill


'''Major card types'''


class 基本牌(CardType):
    class_ = "基本牌"


class 锦囊牌(CardType):
    class_ = "锦囊牌"


class 装备牌(CardType):
    class_ = "装备牌"
    equip_type = "unknown"
    skills = []
    n_targets = None

    @classmethod
    def get_args(cls, player, cards):
        return []

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards)
        [card] = cards
        if cls.equip_type in player.装备区:
            old_equip = player.装备区[cls.equip_type]
            print(f"{player}装备区的牌{old_equip}被弃置")
            game.lose_card(player, old_equip, "装", "弃置", event)
            game.table.append(old_equip)
        game.table.remove(card)
        player.装备区[cls.equip_type] = card


'''Minor card types'''


def _has_equip(player, equip):
    for card in player.装备区.values():
        if issubclass(card.type, equip):
            return True
    return False


class 杀(基本牌):
    damage_type = None

    @classmethod
    def use_range(cls, player, cards):
        return player.attack_range()

    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return player is not target

    @classmethod
    def can_use(cls, player, cards):
        game = player.game
        has_quota = game.attack_quota > 0
        has_quota = game.trigger_skills(Event(player, "test_attack_quota"), has_quota)  # 诸葛连弩, 咆哮
        if not has_quota:
            return False
        return super().can_use(player, cards)

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        if player is game.current_player():  # This test is needed for 借刀杀人, 乱武, 明策, etc.
            game.attack_quota -= 1
        for target in args:
            if not target.is_alive():
                continue
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟
            dodged, _ = game.ask_for_response(target, 闪, event, "请选择是否用闪来响应杀")
            damaged = not dodged
            if dodged:  # 贯石斧, 青龙偃月刀, 猛进, 谋溃
                damaged = game.trigger_skills(Event(player, "attack_dodged", event, target=target), False)
            if damaged:
                n = 2 if player.drunk else 1
                game.damage(target, n, player, event, cls.damage_type)
        player.drunk = False


class 闪(基本牌):
    @classmethod
    def can_use(cls, player, cards):
        return False


class 桃(基本牌):
    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return player is target and player.is_wounded()

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        for target in args:
            if not target.is_alive():
                continue
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟
            game.recover(target, 1, event)


class 即时锦囊(锦囊牌):
    pass


class 延时锦囊(锦囊牌):
    @classmethod
    def hit(cls, judgment):
        return False

    @classmethod
    def hit_effect(cls, card, game):
        print(f"{card}进入了弃牌堆")

    @classmethod
    def miss_effect(cls, card, game):
        print(f"{card}进入了弃牌堆")

    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return cls.__name__ not in target.判定区

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        [card] = cards
        [target] = args
        player.game.table.remove(card)
        target.判定区[cls.__name__] = card


class 武器(装备牌):
    equip_type = "武器"
    range = 2


class 防具(装备牌):
    equip_type = "防具"


class 进攻坐骑(装备牌):
    equip_type = "-1坐骑"


class 防御坐骑(装备牌):
    equip_type = "+1坐骑"


'''Species'''


class 无懈可击(即时锦囊):
    """
    当一张锦囊牌对一名角色生效前或一张【无懈可击】生效前，对此牌使用。抵消此牌对该角色或该【无懈可击】的效果。
    """
    @classmethod
    def can_use(cls, player, cards):
        return False


class 过河拆桥(即时锦囊):
    """
    出牌阶段，对一名区域里有牌的其他角色使用。你弃置其区域里的一张牌。
    """
    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return player is not target and target.total_cards("手装判") > 0

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        for target in args:
            if not player.is_alive():
                break
            if not target.is_alive():
                continue
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟, 无言, 鸡肋
            if game.ask_for_nullification(event, target):
                continue
            place, card = game.pick_card(player, target, "手装判", event)
            if not card:  # e.g. target has only one card 无懈可击, he uses it against 过河拆桥, but the 无懈可击 is
                continue  # countered by another 无懈可击, now he has no cards
            print(f"{target}的{place}{card}被弃置")
            game.lose_card(target, card, place[0], "弃置", event)
            game.discard([card])


class 顺手牵羊(即时锦囊):
    """
    出牌阶段，对距离为1的一名区域里有牌的其他角色使用。你获得其区域里的一张牌。
    """
    @classmethod
    def use_range(cls, player, cards):
        return 1

    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return player is not target and target.total_cards("手装判") > 0

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        for target in args:
            if not player.is_alive():
                break
            if not target.is_alive():
                continue
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟, 无言, 鸡肋
            if game.ask_for_nullification(event, target):
                continue
            place, card = game.pick_card(player, target, "手装判", event, f"请选择要从{target}那里获得的牌")
            if not card:  # e.g. target has only one card 无懈可击, he uses it against 顺手牵羊, but the 无懈可击 is
                continue  # countered by another 无懈可击, now he has no cards
            if "手" in place:
                print(f"{player}获得了{target}的一张手牌")
            else:
                print(f"{player}获得了{target}{place}{card}")
            game.lose_card(target, card, place[0], "获得", event)
            player.hand.append(card)


class 无中生有(即时锦囊):
    """
    出牌阶段，对你使用。你摸两张牌。
    """
    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return player is target

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        for target in args:
            if not target.is_alive():
                continue
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟, 无言, 鸡肋
            if game.ask_for_nullification(event, target):
                continue
            game.deal_cards(target, 2)


class 决斗(即时锦囊):
    """
    出牌阶段，对一名其他角色使用。由该角色开始，你与其轮流打出一张【杀】，然后首先未打出【杀】的角色受到另一名角色造成的1点伤害。
    """
    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return player is not target

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        for target in args:
            if not player.is_alive():
                break
            if not target.is_alive():
                continue
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟, 无言, 鸡肋
            if game.ask_for_nullification(event, target):
                continue
            while True:
                provided, _ = game.ask_for_response(target, 杀, event, f"请选择是否用杀来响应{cls.__name__}")
                if not provided:
                    won = True
                    break
                provided, _ = game.ask_for_response(player, 杀, event, f"请选择是否用杀来响应{cls.__name__}")
                if not provided:
                    won = False
                    break
            if won:
                if target.is_alive():
                    game.damage(target, 1, player, event)
            else:
                if player.is_alive():
                    game.damage(player, 1, target, event)


class 借刀杀人(即时锦囊):
    """
    出牌阶段，对一名装备区里有武器牌的其他角色使用。除非该角色对其攻击范围内，由你选择的另一名角色使用一张【杀】，否则将其装备区里的武器牌交给你。
    """
    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        if player is target or "武器" not in target.装备区:
            return False
        game = player.game
        attack_targets = [p for p in game.iterate_live_players() if 杀.target_legal(target, p, [])]
        return len(attack_targets) > 0

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        for target in args:
            if not player.is_alive():
                break
            if not target.is_alive():
                continue
            options = [p for p in game.iterate_live_players() if 杀.target_legal(target, p, [])]
            event2 = core.Event(player, "get_indirect_target", event, whom=target)  # 驱虎, 明策
            attacked = options[player.agent().choose(options, event2, "请选择借刀杀人指定的杀的使用对象")]
            print(f"{player}令{target}对{attacked}出杀")
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟, 无言, 鸡肋
            if game.ask_for_nullification(event, target):
                continue
            ctype, new_cards = game.ask_for_response(target, 杀, event, f"请选择是否用杀来响应{cls.__name__}", verb="使用")
            if ctype:
                ctype.effect(target, new_cards, [attacked])
            else:
                weapon = target.装备区["武器"]
                print(f"{player}获得了{target}的武器牌{weapon}")
                game.lose_card(target, weapon, "装", "获得", event)
                player.hand.append(weapon)


class 南蛮入侵(即时锦囊):
    """
    出牌阶段，对所有其他角色使用。每名目标角色需打出一张【杀】，否则受到你造成的1点伤害。
    """
    n_targets = None

    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return target is not player

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        for target in args:
            if not target.is_alive():
                continue
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟, 无言, 鸡肋
            if game.ask_for_nullification(event, target):
                continue
            provided, _ = game.ask_for_response(target, 杀, event, f"请选择是否用杀来响应{cls.__name__}")
            if not provided:
                game.damage(target, 1, player, event)


class 五谷丰登(即时锦囊):
    """
    出牌阶段，对所有角色使用。你亮出牌堆顶等同于目标角色数的牌。每名目标角色获得其中的一张。
    """
    n_targets = None

    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return True

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        cards_to_choose = [game.draw_from_deck() for _ in range(len(game.alive))]
        print("亮出了" + "、".join(str(c) for c in cards_to_choose))
        for target in args:
            if not target.is_alive():
                continue
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟, 无言, 鸡肋
            if game.ask_for_nullification(event, target):
                continue
            card = cards_to_choose[target.agent().choose(cards_to_choose, event, "请选择获得的牌")]
            target.hand.append(card)
            print(f"{target}从{cls.__name__}获得了{card}")
            cards_to_choose.remove(card)
        if cards_to_choose:
            print(f"{'、'.join(str(c) for c in cards_to_choose)}进入了弃牌堆")
            game.discard(cards_to_choose)  # cards may be left over due to 无懈可击 or skills


class 桃园结义(即时锦囊):
    """
    出牌阶段，对所有角色使用。每名目标角色回复1点体力。
    """
    n_targets = None

    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return target.is_wounded()

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        for target in args:
            if not target.is_alive():
                continue
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟, 无言, 鸡肋
            if game.ask_for_nullification(event, target):
                continue
            game.recover(target, 1, event)


class 万箭齐发(即时锦囊):
    """
    出牌阶段，对所有其他角色使用。每名目标角色需打出一张【闪】，否则受到你造成的1点伤害。
    """
    n_targets = None

    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return target is not player

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        for target in args:
            if not target.is_alive():
                continue
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟, 无言, 鸡肋
            if game.ask_for_nullification(event, target):
                continue
            provided, _ = game.ask_for_response(target, 闪, event, f"请选择是否用闪来响应{cls.__name__}")
            if not provided:
                game.damage(target, 1, player, event)


class 乐不思蜀(延时锦囊):
    """
    出牌阶段，对一名其他角色使用。将【乐不思蜀】置入该角色的判定区，若判定结果不为♥，则其跳过出牌阶段。
    """
    @classmethod
    def hit(cls, judgment):
        return judgment.suit != "♥"

    @classmethod
    def hit_effect(cls, card, game):
        game.skipped.add("出牌阶段")
        print(f"{cls.__name__}生效，将跳过出牌阶段")

    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return target is not player


class 闪电(延时锦囊):
    """
    出牌阶段，对你使用。将【闪电】置入你的判定区。若判定结果为♠2-9，则目标角色受到3点雷电伤害。若判定不为此结果，将之置入其下家的判定区。
    """
    @classmethod
    def hit(cls, judgment):
        return judgment.suit == "♠" and 2 <= judgment.rank_value() <= 9

    @classmethod
    def hit_effect(cls, card, game):
        player = game.current_player()
        event = UseCardEvent(None, cls, [card], [player])
        game.damage(player, 3, None, event, "雷")

    @classmethod
    def miss_effect(cls, card, game):
        player = game.current_player().next()
        while not cls.target_legal(player, player, [card]):
            player = player.next()
        if player is game.current_player():
            return  # This is for when every player alive has a 闪电 over their head
        game.table.remove(card)
        player.判定区[cls.__name__] = card
        print(f"{card}进入了{player}的判定区")

    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return target is player


class 诸葛连弩特效(Skill):
    """
    锁定技，你使用【杀】无次数限制。
    """
    def can_use(self, player, event):
        if event.who is not player:
            return False
        if event.what == "test_attack_quota":
            return True
        return event.what == "use_card" and issubclass(event.card_type, 杀)

    def use(self, player, event, data=None):
        if event.what == "test_attack_quota":
            return True
        # event.what == "use_card
        game = player.game
        if game.attack_quota <= 0 and player is game.current_player():
            print(f"{player}发动了{self}，额外出杀")


class 诸葛连弩(武器):
    range = 1
    skills = [诸葛连弩特效()]


class 青釭剑特效(Skill):
    """
    锁定技，当你使用【杀】指定一个目标后，你令其防具无效。
    """
    def can_use(self, player, event):
        if event.what != "test_armor_disabled":
            return False
        event0 = event.cause
        return event0.who is player and event0.what == "use_card" and issubclass(event0.card_type, 杀)

    def use(self, player, event, data=None):
        print(f"{player}的武器{self}被触发，无视了{event.who}的防具")
        return True


class 青釭剑(武器):
    range = 2
    skills = [青釭剑特效()]


class 雌雄双股剑特效(Skill):
    """
    当你使用【杀】指定与你性别不同的一个目标后，你可以令其选择一项：1. 弃置一张手牌；2. 令你摸一张牌。
    """
    def can_use(self, player, event):
        if not (event.who is player and event.what == "use_card" and issubclass(event.card_type, 杀)):
            return False
        for target in event.targets:
            if player.male != target.male:
                return True
        return False

    def use(self, player, event, data=None):
        game = player.game
        for target in event.targets:
            use_skill_event = UseSkillEvent(player, self, [target], event)
            if 0 == player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动{self}"):
                continue
            print(f"{player}发动了{self}，令{target}选择弃一张手牌或令其摸一张牌")
            options = ["令其摸一张牌"]
            if target.hand:
                options.append("弃一张手牌")
            choice = target.agent().choose(options, use_skill_event, "雌雄双股剑的武器特效发动，请选择")
            if choice == 0:
                game.deal_cards(player, 1)
            else:
                hand = target.hand
                card = hand[target.agent().choose(hand, use_skill_event, "请选择弃置的牌")]
                print(f"{target}弃置了{card}")
                game.lose_card(target, card, "手", "弃置", use_skill_event)
                game.discard([card])


class 雌雄双股剑(武器):
    range = 2
    skills = [雌雄双股剑特效()]


class 寒冰剑特效(Skill):
    """
    当你使用【杀】对目标角色造成伤害时，若该角色有牌，则你可以防止此伤害，然后你依次弃置其两张牌。
    """
    def can_use(self, player, event):
        if not (event.who is player and event.what == "造成伤害时"):
            return False
        event0 = event.cause.cause  # 造成伤害时 <- damage <- use_card
        if not (event0.who is player and event0.what == "use_card" and issubclass(event0.card_type, 杀)):
            return False
        target = event.cause.whom
        return target.total_cards() > 0

    def use(self, player, event, data=None):
        if data <= 0:
            return data
        game = player.game
        target = event.cause.whom
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动{self}，防止伤害并弃置{target}的两张牌"):
            return data
        for _ in range(2):
            place, card = game.pick_card(player, target, "手装", event=use_skill_event)
            if not card:
                break
            print(f"{player}发动了{self}，弃置了{target}的{place}{card}")
            game.lose_card(target, card, place[0], "弃置", use_skill_event)
            game.discard([card])
        return 0


class 寒冰剑(武器):
    range = 2
    skills = [寒冰剑特效()]


class 贯石斧特效(Skill):
    """
    当你使用的【杀】被目标角色使用的【闪】抵消后，你可以弃置两张牌。若如此做，此【杀】依然会造成伤害。
    """
    def can_use(self, player, event):
        return event.who is player and event.what == "attack_dodged" and player.total_cards() >= 3  # 贯石斧 cannot be discarded

    def use(self, player, event, data=None):
        game = player.game
        target = event.args["target"]
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if not player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动{self}，弃两张牌使得杀强制命中"):
            return False
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = [(place, card) for (place, card) in player.cards(return_places=True)
                   if card is not player.装备区["武器"]]  # 贯石斧 cannot be discarded
        discarded = [options[i] for i in
                     player.agent().choose_many(options, 2, cost_event, f"请选择发动{self}弃置的牌")]
        for place, card in discarded:
            print(f"{player}发动了{self}，弃置了{place}{card}")
            game.lose_card(player, card, place[0], "弃置", cost_event)
            game.discard([card])
        return True


class 贯石斧(武器):
    range = 3
    skills = [贯石斧特效()]


class 青龙偃月刀特效(Skill):
    """
    当你使用的【杀】被目标角色使用的【闪】抵消后，你可以对其使用一张【杀】。
    """
    def can_use(self, player, event):
        return event.who is player and event.what == "attack_dodged"

    def use(self, player, event, data=None):
        game = player.game
        target = event.args["target"]
        event = UseSkillEvent(player, self, [target], event)
        ctype, new_cards = game.ask_for_response(player, 杀, event,
                                                    f"请选择是否发动{self}，对{target}继续出杀", verb="使用")
        if ctype:
            print(f"{player}发动了{self}，对{target}继续出杀")
            ctype.effect(player, new_cards, [target])
        return False  # False because the original 杀 is dodged anyway


class 青龙偃月刀(武器):
    range = 3
    skills = [青龙偃月刀特效()]


class 丈八蛇矛特效(Skill):
    """
    你可以将两张手牌当【杀】使用或打出。
    """
    def can_use(self, player, event):
        if event.who is not player or len(player.hand) < 2:
            return False
        return (event.what is "play" and 杀.can_use(player, []) or
                event.what is "card_asked" and issubclass(杀, event.args["card_type"]))

    def use(self, player, event, data=None):
        game = player.game
        cost_event = Event(player, "use_skill_cost", event, skill=self)
        options = player.cards("手")
        cards = [options[i] for i in player.agent().choose_many(options, 2, cost_event, "请选择两张手牌")]
        if event.what == "play":
            try:
                args = 杀.get_args(player, cards)
            except core.NoOptions:
                print(f"{player}想要使用杀，但中途取消")
                return
            print(f"{player}发动了{self}，将{cards[0]}、{cards[1]}当杀对{'、'.join(str(target) for target in args)}使用")
            for card in cards:
                game.lose_card(player, card, "手", "使用", cost_event)
                game.table.append(card)
            杀.effect(player, cards, args)
        else:  # event.what == "card_asked"
            verb = event.args["verb"]
            print(f"{player}发动了{self}，将{cards[0]}、{cards[1]}当杀{verb}")
            for card in cards:
                game.lose_card(player, card, "手", verb, cost_event)
                game.table.append(card)
            return 杀, cards


class 丈八蛇矛(武器):
    range = 3
    skills = [丈八蛇矛特效()]


class 方天画戟特效(Skill):
    """
    锁定技，若你使用【杀】是你最后的手牌，则此【杀】可以多选择两个目标。
    """
    def can_use(self, player, event):  # pick_additional_targets <- use_card
        if not (event.who is player and event.what == "modify_n_targets" and issubclass(event.args["card_type"], 杀)):
            return False
        cards = event.args["cards"]
        return len(cards) == 1 and cards[0] in player.hand and len(player.hand) == 1

    def use(self, player, event, data=None):
        print(f"{self}被触发，可额外指定两个杀的目标")
        return data + 2


class 方天画戟(武器):
    range = 4
    skills = [方天画戟特效()]


class 麒麟弓特效(Skill):
    """
    当你使用【杀】对目标角色造成伤害时，你可以弃置其装备区里的一张坐骑牌。
    """
    def can_use(self, player, event):
        if not (event.who is player and event.what == "造成伤害时"):
            return False
        event0 = event.cause.cause  # 造成伤害时 <- damage <- use_card
        if not (event0.who is player and event0.what == "use_card" and issubclass(event0.card_type, 杀)):
            return False
        target = event.cause.whom
        return "-1坐骑" in target.装备区 or "+1坐骑" in target.装备区

    def use(self, player, event, data=None):
        game = player.game
        target = event.cause.whom
        use_skill_event = UseSkillEvent(player, self, [target], event)
        if player.agent().choose(["不发动", "发动"], use_skill_event, f"请选择是否发动{self}"):
            options = [target.装备区[key] for key in target.装备区 if key in ("-1坐骑", "+1坐骑")]
            card = options[player.agent().choose(options, use_skill_event, "请选择弃置的牌")]
            print(f"{player}发动{self}，弃置了{target}的{card}")
            game.lose_card(target, card, "装", "弃置", use_skill_event)
            game.discard([card])
        return data


class 麒麟弓(武器):
    range = 5
    skills = [麒麟弓特效()]


class 八卦阵特效(Skill):
    """
    当你需要使用或打出【闪】时，你可以进行判定。若判定结果为红色，则你视为使用或打出一张【闪】。
    """
    def can_use(self, player, event):  # pre_card_asked(player) <- card_asked(player, 闪) <- use_card(user, 杀/万箭齐发)
        return (event.who is player and event.what == "pre_card_asked"
                and issubclass(闪, event.cause.args["card_type"]))

    def use(self, player, event, data=None):
        game = player.game
        ctype, _ = data
        if ctype or game.trigger_skills(Event(player, "test_armor_disabled", event.cause.cause), False):
            return data
        print(f"{player}的{self}被触发，可进行判定")
        game = player.game
        use_skill_event = UseSkillEvent(player, self, None, event)
        if game.autocast or player.agent().choose(["不发动", "发动"], use_skill_event, "请选择是否使用八卦阵"):
            judgment = game.judge(player, use_skill_event)
            if judgment.suit in "♥♦":
                verb = event.cause.args["verb"]
                print(f"{player}视为{verb}闪")
                return 闪, []  # dodged
        return None, []


class 八卦阵(防具):
    skills = [八卦阵特效()]


class 仁王盾特效(Skill):
    """
    锁定技，黑色的【杀】对你无效。
    """
    def can_use(self, player, event):  # test_card_nullify(player) <- use_card(attacker, 杀)
        return (event.who is player and event.what == "test_card_nullify"
                and issubclass(event.cause.card_type, 杀) and core.color(event.cause.cards) == "black")

    def use(self, player, event, data=None):
        game = player.game
        disabled = game.trigger_skills(Event(player, "test_armor_disabled", event.cause), False)
        if disabled:
            return data
        print(f"{player}的{self}被触发，黑杀无效")
        return True


class 仁王盾(防具):
    skills = [仁王盾特效()]


class 赤兔(进攻坐骑):
    pass


class 大宛(进攻坐骑):
    pass


class 紫骍(进攻坐骑):
    pass


class 的卢(防御坐骑):
    pass


class 绝影(防御坐骑):
    pass


class 爪黄飞电(防御坐骑):
    pass


'''军争篇'''


class 雷杀(杀):
    damage_type = "雷"


class 火杀(杀):
    damage_type = "火"


class 酒(基本牌):
    @classmethod
    def can_use(cls, player, cards):
        game = player.game
        if game.drink_quota <= 0:
            return False
        return super().can_use(player, cards)

    @classmethod
    def get_args(cls, player, cards):
        return []

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        if player is game.current_player():
            game.drink_quota -= 1
        player.drunk = True


class 铁索连环(即时锦囊):
    """
    出牌阶段，对一至两名角色使用。目标角色横置或重置。（被横置的角色处于“连环状态”）
    重铸：出牌阶段，你可以将此牌置入弃牌堆，然后摸一张牌。
    """
    n_targets = 2
    can_recast = True

    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return True

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        for target in args:
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟, 无言, 鸡肋
            if game.ask_for_nullification(event, target):
                continue
            game.chain(target, event)


class 火攻(即时锦囊):
    """
    出牌阶段，对一名有手牌的角色使用。该角色展示一张手牌，然后若你弃置与之花色相同的一张手牌，则你对其造成1点火焰伤害。
    """
    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return target.hand

    @classmethod
    def effect(cls, player, cards, args):
        super().effect(player, cards, args)
        game = player.game
        event = UseCardEvent(player, cls, cards, args)
        cost_event = Event(player, "use_card_cost", event)
        for target in args:
            if game.trigger_skills(Event(target, "test_card_nullify", event), False):
                continue  # 仁王盾, 藤甲, 享乐, 毅重, 祸首, 巨象, 智迟, 无言, 鸡肋
            if game.ask_for_nullification(event, target):
                continue
            card_shown = target.hand[target.agent().choose(target.hand, event, f"请展示一张手牌")]
            print(f"{target}展示了手牌{card_shown}")
            options = [None] + player.cards("手", suits=card_shown.suit)
            card_discard = options[player.agent().choose(options, cost_event, f"请选择弃置的手牌")]
            if card_discard:
                print(f"{player}弃置了手牌{card_discard}")
                game.lose_card(player, card_discard, "手", "弃置", cause=cost_event)
                game.table.append(card_discard)
                game.damage(target, 1, player, event, "火")


class 兵粮寸断(延时锦囊):
    """
    出牌阶段，对距离为1的一名其他角色使用。将【兵粮寸断】置入该角色的判定区，若判定结果不为♣，则其跳过摸牌阶段。
    """
    @classmethod
    def use_range(cls, player, cards):
        return 1

    @classmethod
    def hit(cls, judgment):
        return judgment.suit != "♣"

    @classmethod
    def hit_effect(cls, card, game):
        game.skipped.add("摸牌阶段")
        print(f"{cls.__name__}生效，将跳过摸牌阶段")

    @classmethod
    def target_legal(cls, player, target, cards):
        if not super().target_legal(player, target, cards):
            return False
        return target is not player


class 古锭刀特效(Skill):
    """
    锁定技，当你使用【杀】对目标角色造成伤害时，若该角色没有手牌，则此伤害+1。
    """
    def can_use(self, player, event):  # 造成伤害时 <- damage <- use_card
        if not (event.who is player and event.what == "造成伤害时" and not event.cause.whom.hand):
            return False
        event0 = event.cause.cause
        return event0.what == "use_card" and issubclass(event0.card_type, 杀)

    def use(self, player, event, data=None):
        if data > 0:
            print(f"{player}的{self}被触发，伤害+1")
            return data + 1
        else:
            return data


class 古锭刀(武器):
    range = 2
    skills = [古锭刀特效()]


class 朱雀羽扇特效(Skill):
    """
    当你使用普通【杀】时，你可以将此【杀】改为火【杀】。
    """

    def can_use(self, player, event):
        if not (event.who is player and event.what == "play" and 火杀.can_use(player, [])):
            return False
        cards = [card for card in player.hand if card.type == 杀]
        return bool(cards)  # TODO: 神速, 武圣

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        cost_event = Event(player, "use_skill_cost", use_skill_event)
        options = [card for card in player.hand if card.type == 杀]
        card = options[player.agent().choose(options, cost_event, "请选择一张普通杀")]
        args = 火杀.get_args(player, [card])
        print(f"{player}发动了{self}，将{card}当火杀对{'、'.join(str(target) for target in args)}使用")
        game.lose_card(player, card, "手", "使用", cost_event)
        game.table.append(card)
        火杀.effect(player, [card], args)


class 朱雀羽扇(武器):
    range = 4
    skills = [朱雀羽扇特效()]


class 藤甲特效(Skill):
    """
    锁定技，【南蛮入侵】、【万箭齐发】和普通【杀】对你无效；当你受到火焰伤害时，此伤害+1。
    """
    def can_use(self, player, event):
        if event.who is not player:
            return False
        if event.what == "test_card_nullify":  # test_card_nullify <- use_card
            return issubclass(event.cause.card_type, (南蛮入侵, 万箭齐发)) or \
                   issubclass(event.cause.card_type, 杀) and event.cause.card_type.damage_type is None
        elif event.what == "受到伤害时":  # 受到伤害时 <- damage
            return event.cause.type == "火"
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        if event.what == "test_card_nullify":
            disabled = game.trigger_skills(Event(player, "test_armor_disabled", event.cause), False)
            if disabled:
                return data
            print(f"{player}的{self}被触发，{event.cause.card_type.__name__}无效")
            return True
        # event.what == "受到伤害时"
        disabled = game.trigger_skills(Event(player, "test_armor_disabled", event.cause.cause), False)  # test for 青釭剑
        if disabled:  # 受到伤害时 <- damage <- use_card
            return data
        else:
            if data > 0:
                print(f"{player}的{self}被触发，伤害+1")
                return data + 1
            else:
                return data


class 藤甲(防具):
    skills = [藤甲特效()]


class 白银狮子特效(Skill):
    """
    锁定技，当你受到伤害时，若伤害值大于1，则你将伤害值改为1；当你失去装备区里的【白银狮子】后，你回复1点体力。
    """
    def can_use(self, player, event):
        if event.who is not player:
            return False
        if event.what == "受到伤害时":  # 受到伤害时 <- damage
            return True
        elif event.what == "lose_card":
            return event.zone == "装" and player.is_wounded() and self in event.card.type.skills
            # TODO: This doesn't work now because skills of equips that doesn't belong to any player can't trigger
        else:
            return False

    def use(self, player, event, data=None):
        game = player.game
        use_skill_event = UseSkillEvent(player, self, cause=event)
        if event.what == "受到伤害时":
            disabled = game.trigger_skills(Event(player, "test_armor_disabled", event.cause.cause),
                                           False)  # test for 青釭剑
            if disabled:  # 受到伤害时 <- damage <- use_card
                return data
            if data > 1:
                print(f"{player}的{self}被触发")
                return 1
            else:
                return data
        # event.what == "lose_card"
        print(f"{player}的{self}被触发")
        game.recover(player, 1, use_skill_event)


class 白银狮子(防具):
    skills = [白银狮子特效()]


class 骅骝(防御坐骑):
    pass


def get_cardtype(name):
    try:
        card_type = globals()[name]
        if not issubclass(card_type, CardType):
            raise KeyError
        return card_type
    except KeyError:
        return None
