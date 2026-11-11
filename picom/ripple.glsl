#version 330
// Pixel ripple for opening windows (used by the last rule in picom.conf).
//
// picom animates the window's opacity 0 -> 1 when it opens; this shader turns that
// into a ripple instead of a fade: the window appears cell by cell from its centre
// outwards. The wavefront is a band of randomly popping pixels that shine brighter
// and push the image outwards a little, like a ripple on water. Once opacity is past
// FULL the window is drawn solid, like picom's default shader at full opacity.

in vec2 texcoord;            // pixel position inside the window
uniform sampler2D tex;       // window contents
uniform float opacity;       // 0..1, animated by the "open" script

vec4 default_post_processing(vec4 c);

const float CELL = 6.0;      // size of one "pixel" in screen pixels
const float BAND = 0.30;     // width of the wavefront, as a fraction of the window radius
const float SHINE = 0.45;    // how much brighter pixels are on the wavefront
const float PUSH = 2.0;      // how far (in cells) the wavefront pushes the image
const float FULL = 0.8;      // opacity at which the ripple is done (window frames use 0.9)

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

vec4 window_shader() {
    vec2 size = textureSize(tex, 0);
    float p = clamp(opacity / FULL, 0.0, 1.0);
    if (p >= 1.0) {
        // Ripple done: draw the window solid. Dividing the opacity back out skips the
        // see-through tail of the 0 -> 1 animation (and makes window borders fully
        // opaque instead of frame-opacity's 0.9).
        return default_post_processing(texture2D(tex, texcoord / size, 0)) / max(opacity, 0.001);
    }

    vec2 cell = floor(texcoord / CELL);
    vec2 centre = floor(size / (2.0 * CELL));
    vec2 rel = cell - centre;
    float r = length(rel) / max(length(centre), 1.0);   // 0 at centre, ~1 at the corners

    // wave radius sweeps from just before the centre to past the corners
    float front = p * (1.0 + 2.0 * BAND) - BAND;
    float d = (front - r) / BAND;                         // <0 ahead of the wave, >1 behind it
    if (d < hash(cell)) {
        return vec4(0.0);                                 // not revealed yet
    }

    if (d >= 1.0) {
        return texture2D(tex, texcoord / size, 0);        // behind the wave: sharp, opaque
    }

    // on the wavefront: push the image outwards by whole cells and make it shine
    float wave = 1.0 - d;
    vec2 push = floor(normalize(rel + vec2(0.001)) * PUSH * wave + 0.5) * CELL;
    vec2 at = clamp(cell * CELL + CELL * 0.5 - push, vec2(0.5), size - 0.5);
    vec4 c = texture2D(tex, at / size, 0);                // one sample per cell = chunky pixels
    c.rgb = mix(c.rgb, vec3(c.a), SHINE * wave);          // brighten (premultiplied alpha)
    return c;
}
