import React from 'react';

/** Tracks whether a CSS media query currently matches, e.g. '(min-width: 640px)'. */
export const useMediaQuery = (query: string): boolean => {
  const getMatch = () => {
    try {
      return window.matchMedia(query).matches;
    } catch {
      return false;
    }
  };

  const [matches, setMatches] = React.useState(getMatch);

  React.useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);

  return matches;
};
