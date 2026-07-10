# Design System: Maya Smart Home Mobile App
**Project ID:** zlen2024/Maya-Smarthome-AI

## 1. Visual Theme & Atmosphere
The Maya Smart Home mobile app utilizes a **Dark-Only Aurora Glassmorphism** design theme. The overall "vibe" is futuristic, sleek, organic, and premium.
- **Density**: Airy with generous whitespace, giving the UI elements room to breathe.
- **Glassmorphic Depth**: Standard solid UI cards are replaced with translucent frosted glass surfaces. These surfaces float over a deep space backdrop containing colorful, slowly drifting, and pulsing "aurora" orbs.
- **Glow Highlights**: Interactive active states (like turned-on switch channels or active panels) emit a soft, vibrant glow of the user's selected accent color, making the interface feel alive and tactile.

---

## 2. Color Palette & Roles

The system uses specific hex color values mapped to functional design roles:

### Base Canvas
* **Deep Space Navy-Black (#060A14)**: The solid background color sitting behind all pages.

### Core Ambient Orbs (Drifting Background Particles)
* **Vibrant Violet (#7C3AED)**: Primary ambient glow orb situated in the top-left area.
* **Bright Sky-Blue (#0EA5E9)**: Secondary ambient glow orb situated in the top-right area.
* **Deap Teal (#0D9488)**: Subtle warm wash orb situated in the bottom-middle area for depth.

### Dynamic Theme Presets (User Selectable)
The user can select from three accent identities which change the highlight glows and background canvas color:

1. **Aurora (Cyan Preset)**:
   * **Accent Highlight Color (#22D3EE)**: Bright cyan color for active switches, toggles, and glow frames.
   * **Background Base (#060A14)**: Deepest navy-black.
   * **Orb Colors**: Vibrant Violet (#7C3AED), Bright Sky-Blue (#0EA5E9), and Deep Teal (#0D9488).

2. **Obsidian (Lime Preset)**:
   * **Accent Highlight Color (#BEF264)**: Electric lime green for highlights.
   * **Background Base (#0B0B0C)**: Deep charcoal-black.
   * **Orb Colors**: Dark Zinc (#3F3F46), Midnight Blue (#1F2937), and Lime Depth (#4D7C0F).

3. **Spectrum (Magenta Preset)**:
   * **Accent Highlight Color (#F0569E)**: Electric pink/magenta highlights.
   * **Background Base (#140A17)**: Deep plum-black.
   * **Orb Colors**: Magenta Rose (#C026D3), Flame Orange (#EA580C), and Indigo Depth (#4F46E5).

### Glass & Borders
* **Frosted Tint (rgba(255, 255, 255, 0.14))**: Translucent overlay for cards.
* **Frosted Border (rgba(255, 255, 255, 0.18))**: A paper-thin white border framing glass cards.
* **Active Glow Border (rgba(accent, 0.65))**: Colored border framing active or glowing cards.

---

## 3. Typography Rules
The typography utilizes the clean, legible sans-serif font family **Roboto** (or default system font) with high contrast and structured hierarchy:

* **Hero Screen Titles**: Extra-bold (`FontWeight.w800`), size 21px to 26px, compressed letter-spacing (-0.3px) for an impactful layout header (e.g. house name).
* **Section Headers / Tab Subtitles**: Semi-bold (`FontWeight.w500`), size 12px to 14px, muted white (`opacity(0.55)`) to serve as contextual metadata helper.
* **Component Titles**: Bold (`FontWeight.w700`), size 16px, crisp white color.
* **Body / Label Text**: Regular or Medium (`FontWeight.w500`), size 14px, white color.
* **System Identifiers / Metadata**: Monospace font family, size 11px, muted white (`opacity(0.35)`) (e.g. ESP32 Device IDs).

---

## 4. Component Stylings

### Cards & Containers (`GlassSurface`)
* **Frosted Blur**: Rendered with built-in hardware-accelerated BackdropFilter blur (`sigmaX: 18, sigmaY: 18`).
* **Geometry**: Generously rounded corners (`BorderRadius.circular(18)` for standard cards, `BorderRadius.circular(28)` for floating bar containers).
* **Borders**: Fixed width of 1px with `#FFFFFF` at `0.18` opacity.
* **Active Glow Shadows**: When glowing, cards draw a soft diffuse box shadow using the active accent color (`opacity: 0.30, blurRadius: 32, spreadRadius: -2`).

### Buttons
* **Primary Actions**: Full width with pill-shaped corners (`BorderRadius.circular(16)`), colored in the active accent color with contrasting dark text for readability.
* **Tonal/Secondary Buttons**: Floating transparent cards with small borders and colored text.

### Inputs & Forms
* **Text Fields**: Filled with a translucent white tint (`rgba(255, 255, 255, 0.06)`), without stroke borders (`BorderSide.none`), and rounded corners (`BorderRadius.circular(16)`).

---

## 5. Layout Principles
* **Whitespace Rhythm**: Large vertical padding (`20px` left/right, `24px` bottom) separates main layout sections.
* **Grid Flow**: Cards span the full width of the screen content viewport with uniform spacing gaps of `12px` to `16px` to maintain a structural stack.
* **Floating Bars**: Tab navigation bars and chat text inputs float as separate glass capsules on the screen, letting elements scroll underneath them naturally.
