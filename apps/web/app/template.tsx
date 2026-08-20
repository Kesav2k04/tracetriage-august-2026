/**
 * The wrapper that remounts on every navigation, which is what makes a page transition.
 *
 * A `layout.tsx` persists across routes, so an animation declared there runs once, on the
 * first load, and never again. A `template.tsx` is re-created for each route, so the class
 * below re-enters every time a reader moves between the queue, an observation and the
 * evaluation. That is the whole mechanism: no library, no experimental flag, no JavaScript
 * beyond what the router already does.
 *
 * It fades and does not move. A `transform` here would become the containing block for every
 * `position: sticky` descendant, and two of them are load-bearing: the waterfall controls on
 * an observation page and the replay clock. A crossfade costs nothing and cannot break them.
 *
 * `apps/web/app/globals.css` holds the rule, inside a reduced-motion query.
 */
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="route-enter">{children}</div>;
}
