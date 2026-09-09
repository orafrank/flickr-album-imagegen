# Flickr Album ImageGen

A personal Codex skill that downloads an ordered range of photos from a public Flickr album and transforms each photo independently with a user-provided image-generation prompt.

## Install

Clone this repository into your personal Codex skills directory:

```bash
git clone https://github.com/orafrank/flickr-album-imagegen.git ~/.codex/skills/flickr-album-imagegen
```

Restart Codex, then ask it to use `flickr-album-imagegen` with:

- a public Flickr album URL;
- a page or photo range;
- an image transformation prompt.

Example:

> Use flickr-album-imagegen to process the first 10 photos from this Flickr album with the following poster prompt: ...

## Notes

- Each source photo is generated and saved independently.
- Album order is scoped to the exact URL, including `/page2` and later pages.
- Private albums and access-control bypasses are not supported.
- Image generation requires an image-generation tool available in the user's Codex environment.

