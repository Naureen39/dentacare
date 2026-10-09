/** Facts about the clinic that appear on many pages. Fictional: this is a demonstration site. */

export const clinic = {
  name: 'Meridian Dental Care',
  tagline: 'Exceptional dental care for every stage of life',
  phone: '(555) 010-0199',
  phoneHref: 'tel:+15550100199',
  emergencyPhone: '(555) 010-0911',
  emergencyHref: 'tel:+15550100911',
  email: 'frontdesk@meridian.test',
  address: {
    street: '1200 Harbor View Drive, Suite 300',
    city: 'Springfield',
    region: 'NY',
    postalCode: '10001',
    country: 'US',
  },
  geo: { lat: 40.7506, lng: -73.9935 },
  founded: 2009,
  /** Times of day on the site are always the clinic's, whatever the visitor's time zone. */
  timeZone: 'America/New_York',
  siteUrl: import.meta.env.VITE_SITE_URL ?? 'https://meridian.example',
} as const

export const fullAddress = `${clinic.address.street}, ${clinic.address.city}, ${clinic.address.region} ${clinic.address.postalCode}`

export const directionsUrl = `https://www.openstreetmap.org/directions?to=${clinic.geo.lat}%2C${clinic.geo.lng}`

/** Opening hours, as shown in the footer and on the contact page, and as schema.org data. */
export const hours = [
  {
    days: 'Monday to Friday',
    opens: '8:00 AM',
    closes: '6:00 PM',
    note: 'Lunch break 12:30 to 1:30 PM',
    schema: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'],
    from: '08:00',
    to: '18:00',
  },
  {
    days: 'Saturday',
    opens: '9:00 AM',
    closes: '2:00 PM',
    note: '',
    schema: ['Saturday'],
    from: '09:00',
    to: '14:00',
  },
  {
    days: 'Sunday',
    opens: '',
    closes: '',
    note: 'Closed. Emergency line open',
    schema: [],
    from: '',
    to: '',
  },
] as const

export const stats = {
  years: new Date().getFullYear() - clinic.founded,
  patients: 4500,
  specialists: 7,
  rating: 4.8,
  reviews: 212,
}

export const socialLinks = [
  { name: 'Facebook', href: 'https://www.facebook.com/' },
  { name: 'Instagram', href: 'https://www.instagram.com/' },
  { name: 'LinkedIn', href: 'https://www.linkedin.com/' },
  { name: 'YouTube', href: 'https://www.youtube.com/' },
] as const

export const mainNav = {
  patientInfo: [
    { label: 'New patients', to: '/new-patients', text: 'What to expect and what to bring' },
    {
      label: 'Insurance and payment',
      to: '/insurance-and-payment',
      text: 'Plans, self pay and payment plans',
    },
    { label: 'Pricing', to: '/pricing', text: 'Starting prices for common care' },
    { label: 'FAQ', to: '/faq', text: 'Answers to common questions' },
    { label: 'Forms', to: '/new-patients#forms', text: 'Forms to print and bring' },
  ],
  links: [
    { label: 'Our dentists', to: '/dentists' },
    { label: 'Reviews', to: '/reviews' },
    { label: 'About', to: '/about' },
    { label: 'Contact', to: '/contact' },
  ],
} as const

export const legalLinks = [
  { label: 'Privacy policy', to: '/privacy' },
  { label: 'Terms of use', to: '/terms' },
  { label: 'Accessibility', to: '/accessibility' },
  { label: 'Notice of privacy practices', to: '/notice-of-privacy-practices' },
] as const

export const insuranceCategories = [
  {
    title: 'PPO plans',
    text: 'Preferred provider plans let you choose your dentist. We file claims for you and estimate your share before treatment.',
  },
  {
    title: 'HMO style plans',
    text: 'Managed care plans with set copayments. Tell us your plan when you book so we can confirm that we take it.',
  },
  {
    title: 'Self pay',
    text: 'No insurance? You pay at the visit, and we give you the cost in writing before any treatment starts.',
  },
  {
    title: 'Payment plans',
    text: 'Larger treatment can be spread over three equal payments with no interest, arranged at the front desk.',
  },
  {
    title: 'Flexible spending accounts',
    text: 'FSA and HSA cards are accepted for the part of your bill that insurance does not cover.',
  },
  {
    title: 'Children and families',
    text: 'Many plans cover routine care for children in full. We will explain what yours includes.',
  },
] as const

export const homeFaqs = [
  {
    q: 'Do I need insurance to be seen?',
    a: 'No. Many patients pay themselves. We give you a written estimate before treatment and offer payment plans for larger work.',
  },
  {
    q: 'How do I book an appointment?',
    a: 'Book online at any hour, call the front desk, or ask our chat assistant. Online booking shows only the times that are open.',
  },
  {
    q: 'What if I have a dental emergency?',
    a: 'Call our emergency line. We keep time free each day for urgent problems. For trouble breathing, spreading swelling or bleeding that will not stop, call 911.',
  },
  {
    q: 'How often should I have a checkup?',
    a: 'Most people do well with a checkup and cleaning every six months. Your dentist may suggest a different schedule for you.',
  },
  {
    q: 'Can I cancel or change my appointment?',
    a: 'Yes. Use the link in your reminder email or call us. Changes made at least 24 hours ahead are free.',
  },
  {
    q: 'Do you treat children?',
    a: 'Yes. Our pediatric dentist sees children from their first tooth and makes the first visit short and friendly.',
  },
  {
    q: 'I am nervous about the dentist. Can you help?',
    a: 'Yes. Tell us when you book. We go at your pace, explain each step, and offer sedation options when they are right for you.',
  },
  {
    q: 'How long does a first visit take?',
    a: 'About an hour: an examination, x-rays if needed, and time to talk through a plan with your dentist.',
  },
] as const

export const patientJourney = [
  {
    title: 'Book',
    text: 'Choose a time online, by phone or in chat. Confirmation arrives by email.',
  },
  {
    title: 'Visit',
    text: 'A friendly welcome, a careful examination, and an honest conversation about what you need.',
  },
  {
    title: 'Treatment plan',
    text: 'A written plan with the steps, the timing and the cost, before anything begins.',
  },
  {
    title: 'Follow up',
    text: 'Reminders for your next visit and a call if you have questions after treatment.',
  },
] as const

export const pillars = [
  {
    title: 'Experienced specialists',
    text: 'Seven dentists across general, pediatric, orthodontic, endodontic, periodontal, surgical and cosmetic care, under one roof.',
  },
  {
    title: 'Modern technology',
    text: 'Digital x-rays with a fraction of the radiation, clear imaging, and treatment planning on screen so you can see what we see.',
  },
  {
    title: 'Comfort focused care',
    text: 'Unhurried visits, gentle technique, and sedation options for anxious patients.',
  },
  {
    title: 'Transparent pricing',
    text: 'Starting prices on this site and a written estimate before treatment. No surprise bills.',
  },
] as const

export const comfortPoints = [
  'Digital imaging that shows detail clearly with low radiation',
  'Hospital grade sterilization of every instrument, checked and logged',
  'Nitrous oxide and oral sedation for patients who feel anxious',
  'Noise cancelling headphones, blankets and a screen for distraction',
] as const
