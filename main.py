from game import Game

if __name__ == "__main__":
    game = Game([("RANDOM", "ai"), ("RANDOM", "ai"), ("RANDOM", "ai"),
                 ("RANDOM", "ai"), ("左慈", "human"), ("RANDOM", "ai"),
                 ("RANDOM", "ai"), ("RANDOM", "ai"), ("RANDOM", "ai")],
                "军争")
    game.run()
