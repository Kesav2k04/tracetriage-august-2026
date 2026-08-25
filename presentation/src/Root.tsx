import React from "react";
import { Composition } from "remotion";
import "./fonts";
import { Film, FILM_FRAMES } from "./Film";
import { Poster } from "./Poster";
import { FPS, HEIGHT, WIDTH } from "./theme";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="Film"
      component={Film}
      durationInFrames={FILM_FRAMES}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
    {/* The thumbnail is its own composition rather than a frame of the film, because it
        is read at about 160 pixels wide by somebody who has not decided to watch yet. */}
    <Composition
      id="Poster"
      component={Poster}
      durationInFrames={1}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
  </>
);
