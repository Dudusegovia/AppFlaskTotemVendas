const images = [
  'assets/loop1.jpg',
  'assets/loop2.jpg',
  'assets/loop3.jpg',
    'assets/loop4.jpg',
  'assets/loop5.jpg',
  'assets/loop6.jpg',
    'assets/loop7.jpg',
  'assets/loop8.jpg',
  'assets/loop9.jpg'
];

let index = 0;
const banner = document.getElementById('image-loop');

setInterval(() => {
  // fade out
  banner.style.opacity = 0;

  setTimeout(() => {
    // troca a imagem no meio do fade
    index = (index + 1) % images.length;
    banner.src = images[index];
    banner.style.opacity = 1; // fade in
  }, 1000); // tempo deve combinar com o CSS (1s)
}, 3000);
