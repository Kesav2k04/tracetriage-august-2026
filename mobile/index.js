// The entry point Expo's Metro config looks for. `registerRootComponent` is what wires the
// component into whichever host is running it, which is why this file exists at all rather
// than App.tsx being the entry.
import { registerRootComponent } from "expo";

import App from "./src/App";

registerRootComponent(App);
