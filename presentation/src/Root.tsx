import React from "react";
import { Composition } from "remotion";
import "./fonts";
import { Film, FILM_FRAMES } from "./Film";
import { FPS, HEIGHT, WIDTH } from "./theme";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Film"
    component={Film}
    durationInFrames={FILM_FRAMES}
    fps={FPS}
    width={WIDTH}
    height={HEIGHT}
  />
);
