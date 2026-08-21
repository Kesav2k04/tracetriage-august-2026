import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { ease, font, MARGIN, numeric, token } from "./theme";
import type { Claim } from "./claim";

const entrance = Easing.bezier(...ease.entrance);
const standard = Easing.bezier(...ease.standard);

/** 400ms, which is --dur-slow-01 on the console. */
export const REVEAL = 12;

export const progress = (
  frame: number,
  delay: number,
  duration = REVEAL,
  easing = entrance,
): number =>
  interpolate(frame - delay, [0, duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing,
  });

export const Reveal: React.FC<{
  delay?: number;
  rise?: number;
  duration?: number;
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({ delay = 0, rise = 8, duration = REVEAL, style, children }) => {
  const frame = useCurrentFrame();
  const p = progress(frame, delay, duration);
  return (
    <div
      style={{
        ...style,
        opacity: p,
        transform: `translateY(${((1 - p) * rise).toFixed(2)}px)`,
      }}
    >
      {children}
    </div>
  );
};

/** A hairline that draws from the left, the way the console's plate edges do. */
export const Rule: React.FC<{
  delay?: number;
  colour?: string;
  width?: number | string;
  thickness?: number;
}> = ({ delay = 0, colour = token.borderSubtle, width = "100%", thickness = 1 }) => {
  const frame = useCurrentFrame();
  const p = progress(frame, delay, 16, standard);
  return (
    <div
      style={{
        width,
        height: thickness,
        background: colour,
        transform: `scaleX(${p})`,
        transformOrigin: "left center",
      }}
    />
  );
};

export const Eyebrow: React.FC<{ children: React.ReactNode; colour?: string }> = ({
  children,
  colour = token.text03,
}) => (
  <div
    style={{
      fontFamily: font.mono,
      fontSize: 18,
      letterSpacing: 1.6,
      textTransform: "uppercase",
      color: colour,
    }}
  >
    {children}
  </div>
);

export const Heading: React.FC<{ children: React.ReactNode; size?: number }> = ({
  children,
  size = 54,
}) => (
  <h1
    style={{
      fontFamily: font.sans,
      fontWeight: 600,
      fontSize: size,
      lineHeight: 1.15,
      letterSpacing: -0.6,
      color: token.text01,
      margin: 0,
    }}
  >
    {children}
  </h1>
);

export const Body: React.FC<{
  children: React.ReactNode;
  size?: number;
  colour?: string;
  width?: number;
}> = ({ children, size = 26, colour = token.text02, width }) => (
  <p
    style={{
      fontFamily: font.sans,
      fontWeight: 400,
      fontSize: size,
      lineHeight: 1.55,
      color: colour,
      margin: 0,
      maxWidth: width,
    }}
  >
    {children}
  </p>
);

export const Mono: React.FC<{
  children: React.ReactNode;
  size?: number;
  colour?: string;
}> = ({ children, size = 20, colour = token.text03 }) => (
  <span
    style={{
      fontFamily: font.mono,
      fontSize: size,
      color: colour,
      ...numeric,
    }}
  >
    {children}
  </span>
);

/** A measurement. The number in the console's strongest ink, its unit beside it. */
export const Figure: React.FC<{
  value: string;
  unit?: string;
  size?: number;
  colour?: string;
}> = ({ value, unit, size = 84, colour = token.text01 }) => (
  <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
    <span
      style={{
        fontFamily: font.sans,
        fontWeight: 600,
        fontSize: size,
        lineHeight: 1,
        letterSpacing: -1,
        color: colour,
        ...numeric,
      }}
    >
      {value}
    </span>
    {unit ? (
      <span
        style={{
          fontFamily: font.sans,
          fontWeight: 400,
          fontSize: Math.round(size * 0.28),
          color: token.text03,
        }}
      >
        {unit}
      </span>
    ) : null}
  </div>
);

export const Stat: React.FC<{
  figure: string;
  unit?: string;
  caption: React.ReactNode;
  size?: number;
  colour?: string;
}> = ({ figure, unit, caption, size = 84, colour }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
    <Figure value={figure} unit={unit} size={size} colour={colour} />
    <div
      style={{
        fontFamily: font.sans,
        fontSize: 22,
        lineHeight: 1.45,
        color: token.text02,
        maxWidth: 380,
      }}
    >
      {caption}
    </div>
  </div>
);

export const Plate: React.FC<{
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ children, style }) => (
  <div
    style={{
      background: token.ui01,
      border: `1px solid ${token.borderSubtle}`,
      padding: 28,
      ...style,
    }}
  >
    {children}
  </div>
);

/**
 * The verdict markers the console uses: a filled disc for a pass, a hollow ring for
 * a measurement that came back inconclusive, a dash for one that was never run.
 * Shape carries the state so hue never has to.
 */
export const VerdictMark: React.FC<{ verdict: string; size?: number }> = ({
  verdict,
  size = 14,
}) => {
  if (verdict === "PASSED" || verdict === "PRE_PASSED") {
    return (
      <span
        style={{
          width: size,
          height: size,
          borderRadius: size,
          background: token.verdictPassed,
          display: "inline-block",
          flex: "0 0 auto",
        }}
      />
    );
  }
  if (verdict === "NOT_ESTABLISHED") {
    return (
      <span
        style={{
          width: size,
          height: size,
          borderRadius: size,
          border: `2px solid ${token.verdictNotEstablished}`,
          display: "inline-block",
          flex: "0 0 auto",
          boxSizing: "border-box",
        }}
      />
    );
  }
  if (verdict === "FAILED") {
    return (
      <span
        style={{
          width: size,
          height: size,
          borderRadius: size,
          background: token.verdictFailed,
          display: "inline-block",
          flex: "0 0 auto",
        }}
      />
    );
  }
  return (
    <span
      style={{
        width: size,
        height: 2,
        background: token.verdictNotMeasurable,
        display: "inline-block",
        flex: "0 0 auto",
      }}
    />
  );
};

/**
 * The chrome every beat sits in. The bottom line names the receipt the numbers on
 * screen came from, which is the whole argument of the console this film is about.
 */
export const Frame: React.FC<{
  eyebrow: string;
  sources: readonly Claim<unknown>[];
  children: React.ReactNode;
}> = ({ eyebrow, sources, children }) => {
  const files: string[] = [];
  for (const source of sources) {
    if (!files.includes(source.file)) files.push(source.file);
  }
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: token.uiBackground,
        fontFamily: font.sans,
      }}
    >
      <div
        style={{
          position: "absolute",
          left: MARGIN,
          right: MARGIN,
          top: 46,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <Eyebrow colour={token.text02}>{eyebrow}</Eyebrow>
        <Mono size={17} colour={token.text03}>
          TraceTriage
        </Mono>
      </div>
      <div style={{ position: "absolute", left: MARGIN, right: MARGIN, top: 78 }}>
        <Rule delay={0} />
      </div>

      <div
        style={{
          position: "absolute",
          left: MARGIN,
          right: MARGIN,
          top: 132,
          bottom: 116,
        }}
      >
        {children}
      </div>

      <div style={{ position: "absolute", left: MARGIN, right: MARGIN, bottom: 76 }}>
        <Rule delay={0} colour={token.ui02} />
      </div>
      <div
        style={{
          position: "absolute",
          left: MARGIN,
          right: MARGIN,
          bottom: 40,
          display: "flex",
          gap: 28,
          alignItems: "baseline",
        }}
      >
        <Mono size={16} colour={token.text03}>
          read from
        </Mono>
        {files.map((file) => (
          <Mono key={file} size={16} colour={token.text02}>
            {file}
          </Mono>
        ))}
      </div>
    </div>
  );
};
