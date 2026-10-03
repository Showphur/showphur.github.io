# Fun Learning Games 🌈

A collection of simple, kid-friendly learning games, made for my daughter and hosted for free with GitHub Pages.

**Play here:** https://showphur.github.io

## Games

| Game | Folder |
|---|---|
| Counting Stars! ⭐ | [`counting-stars/`](counting-stars/) |
| Math Challenge! ➕➖ | [`math-challenge/`](math-challenge/) |
| Shape Challenge! 🔷🔺 | [`shape-challenge/`](shape-challenge/) |
| Pattern Explorer! 🔠🔄 | [`pattern-game/`](pattern-game/) |
| Quantity Compare! ⚖️ | [`quantity-game/`](quantity-game/) |
| Measurement Explorer! 📏⚖️ | [`measurement-explorer/`](measurement-explorer/) |
| Digital Navigator! 🖱️💻 | [`digital-navigation/`](digital-navigation/) |
| Future Tech Builder! 🤖🚀 | [`tech-builder/`](tech-builder/) |
| Story Generator! 📚✨ | [`story-gen/`](story-gen/) |
| Sorting Game! 🎨📏🔷 | [`sorting-game/`](sorting-game/) |
| Algebra Game! 🍎 | [`algebra-game/`](algebra-game/) |
| Darcy's Game (Adventure Island!) | [`darcys-game/`](darcys-game/) |
| Tiny Terrarium! 🌿 | [`terrarium/`](terrarium/) |
| Evolution Terrarium! 🧬 | [`evolution-terrarium/`](evolution-terrarium/) |

Shared sound effects live in [`sounds/`](sounds/).

## How it's organised

- `index.html` is the home page, with a button for each game.
- Each game is a single `index.html` file in its own folder.

## Adding a new game

1. Create a new folder, e.g. `colour-match/`, with an `index.html` inside.
2. Add a button for it in the root `index.html`:
   ```html
   <a href="./colour-match/index.html" class="game-link-button">
       Colour Match! 🎨
   </a>
   ```
3. Add it to the table above.
4. Commit, push, and merge into `main`. GitHub Pages publishes it within a minute or two.
